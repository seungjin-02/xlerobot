"""Serialized transaction: verified release -> snapshots -> atomic switch -> health/rollback."""
import contextlib
import fcntl
import http.cookiejar
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
import urllib.request
import urllib.error
import uuid

from common import UpdateError, SHA, TAG, TERMINAL, atomic_json, manifest, snapshot, switch_link, preserve_ownership


class Runtime:
    """Fixed services and loopback HTTP only. Never execute candidate install/build scripts."""
    def __init__(self, config):
        self.config = Path(config)
        self.client = urllib.request.build_opener(urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def get(self, path, authenticated=False):
        base = 'http://127.0.0.1:8090'
        try:
            with self.client.open(base+path, timeout=10) as response: return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code != 401 or not authenticated: raise
        config = json.loads(self.config.read_text())
        request = urllib.request.Request(base+'/api/pair', data=json.dumps({'pin':config['pin']}).encode(),
            headers={'Content-Type':'application/json','Origin':base})
        with self.client.open(request,timeout=5) as response:
            if json.load(response).get('ok') is not True: raise UpdateError('robot_authentication_failed')
        with self.client.open(base+path,timeout=10) as response: return json.load(response)

    def service(self, verb):
        if verb not in ('start', 'stop'): raise UpdateError('invalid_service_operation')
        try:
            subprocess.run(['systemctl', verb, 'lekiwi-camera.service', 'lekiwi-phone.service'],
                check=True, stdin=subprocess.DEVNULL, capture_output=True, timeout=45)
            for unit in ('lekiwi-camera.service', 'lekiwi-phone.service'):
                r = subprocess.run(['systemctl', 'is-active', unit], capture_output=True, text=True, timeout=5)
                if r.stdout.strip() != ('active' if verb == 'start' else 'inactive'):
                    raise UpdateError('service_state_mismatch')
        except (OSError, subprocess.SubprocessError): raise UpdateError('service_operation_failed') from None

    def idle(self):
        status = self.get('/api/status', authenticated=True)
        rec = status.get('recording', {})
        if (type(status.get('armed')) is not bool or type(status.get('available')) is not bool or 'motor_ready' not in status or
                (status['motor_ready'] is not None and type(status['motor_ready']) is not bool) or
                status.get('motor_ready') is True or
                type(status.get('other_publishers')) is not int or status['other_publishers'] != 0 or
                type(rec.get('active')) is not bool or type(rec.get('finishing')) is not bool or
                status['armed'] or rec['active'] or rec['finishing']):
            raise UpdateError('robot_not_idle_or_state_unknown')
        return status

    def health(self, expected_commit):
        client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for attempt in range(15):
            try:
                if self.get('/health') != {'ok':True,'demo':False}: raise UpdateError('runtime_health_failed')
                self.idle()
                if self.get('/api/system',authenticated=True)['git']['commit'] != expected_commit:
                    raise UpdateError('runtime_commit_mismatch')
                with client.open('http://127.0.0.1:8080/snapshot', timeout=5) as response:
                    image = response.read(2_000_001)
                    if not image.startswith(b'\xff\xd8') or not image.endswith(b'\xff\xd9') or len(image)>2_000_000:
                        raise UpdateError('front_camera_failed')
                return
            except (OSError, ValueError, KeyError, UpdateError):
                if attempt == 14: raise UpdateError('post_update_verification_failed') from None
                time.sleep(1)


class Engine:
    def __init__(self, root, sources, runtime, paths):
        self.root, self.sources, self.runtime = Path(root), sources, runtime
        self.paths = {key: Path(value) for key, value in paths.items()}
        self.current = self.root/'current'
        self.root.mkdir(parents=True, exist_ok=True)
        self.mutex = threading.Lock()
        self.state = json.loads((self.root/'journal.json').read_text()) if (self.root/'journal.json').exists() else {'phase':'idle'}
        if not (self.root/'journal.json').exists(): self.publish('idle')

    def publish(self, phase, **fields):
        self.state = {**self.state, **fields, 'phase':phase, 'updated_at':time.time()}
        atomic_json(self.root/'journal.json', self.state)
        public = {k:self.state[k] for k in ('phase','updated_at','tag','commit','error') if k in self.state}
        atomic_json(self.root/'status.json', public, 0o644)

    def baseline(self):
        if not self.current.is_symlink(): raise UpdateError('managed_installation_required')
        source = self.current.resolve()
        if source.parent != (self.root/'releases').resolve() or not SHA.fullmatch(source.name):
            raise UpdateError('invalid_current_release')
        return source.name

    @contextlib.contextmanager
    def exclusive(self):
        if not self.mutex.acquire(blocking=False): raise UpdateError('update_busy')
        lock = None
        try:
            lock = (self.root/'operation.lock').open('a+')
            os.chmod(self.root/'operation.lock', 0o644)
            try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise UpdateError('update_busy') from None
            yield
        finally:
            if lock: lock.close()
            self.mutex.release()

    def reserve(self):
        # The app takes the shared side of this same lock for each mutating action.
        atomic_json(self.root/'maintenance.json', {'blocked':True}, 0o644)

    def release(self):
        (self.root/'maintenance.json').unlink(missing_ok=True)
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)

    def check_unchanged(self, backup):
        for name, path in self.paths.items():
            expected = json.loads((backup/(name+'-manifest.json')).read_text())
            if manifest(path) != expected: raise UpdateError('preserved_data_changed')

    def restore_files(self, backup):
        # Preserve unexpected/new data separately before restoring; never delete it.
        rescue = backup/'post-failure'
        rescue.mkdir(exist_ok=True, mode=0o700)
        for name, path in self.paths.items():
            expected = json.loads((backup/(name+'-manifest.json')).read_text())
            if manifest(path) == expected: continue
            if path.exists():
                snapshot(path, rescue/(name+'-'+uuid.uuid4().hex))
                if expected['exists']:
                    for child in path.iterdir():
                        if child.is_dir() and not child.is_symlink(): shutil.rmtree(child)
                        else: child.unlink()
                else: shutil.rmtree(path)
            if expected['exists']:
                shutil.copytree(backup/name, path, symlinks=True, dirs_exist_ok=True)
                preserve_ownership(backup/name,path)
            if manifest(path) != expected: raise UpdateError('restore_verification_failed')

    def update(self, tag, expected_commit, physical_ack):
        if physical_ack is not True: raise UpdateError('physical_motor_isolation_ack_required')
        if not isinstance(expected_commit, str) or not SHA.fullmatch(expected_commit): raise UpdateError('invalid_expected_commit')
        with self.exclusive():
            if self.state['phase'] not in TERMINAL or (self.root/'maintenance.json').exists():
                raise UpdateError('recovery_required')
            old = self.baseline()
            if not isinstance(tag,str) or not TAG.fullmatch(tag): raise UpdateError('invalid_release_tag')
            self.reserve()
            self.publish('preparing', tag=tag, commit=expected_commit, previous=old, error=None, backup=None)
            stopped = False
            try:
                self.runtime.idle()
                self.sources.refresh()
                release = self.sources.describe(tag, old)
                if release['commit'] != expected_commit or old == expected_commit: raise UpdateError('release_commit_changed_or_already_installed')
                release_dir = self.root/'releases'/expected_commit
                self.sources.extract(expected_commit, release_dir)
                atomic_json(release_dir/'.lekiwi-release.json', {'commit':expected_commit,'tag':tag}, 0o644)
                space = sum(manifest(p)['bytes'] for p in self.paths.values())
                if shutil.disk_usage(self.root).free < space*2+256*1024**2: raise UpdateError('insufficient_backup_space')
                stopped = True
                self.runtime.service('stop')
                backup = self.root/'backups'/uuid.uuid4().hex
                backup.mkdir(parents=True, mode=0o700)
                self.publish('backing_up', backup=str(backup))
                for name, path in self.paths.items():
                    value = snapshot(path, backup/name)
                    atomic_json(backup/(name+'-manifest.json'), value)
                self.publish('switching')
                switch_link(self.current, release_dir)
                self.publish('verifying')
                self.runtime.service('start')
                self.runtime.health(expected_commit)
                self.check_unchanged(backup)
                self.publish('succeeded')
                self.release()
            except Exception as error:
                code = str(error) if isinstance(error, UpdateError) else 'update_io_or_verification_failed'
                try:
                    if stopped:
                        self.runtime.service('stop')
                        switch_link(self.current, self.root/'releases'/old)
                        # Restore only complete snapshots; a failed backup never changed live data.
                        if self.state['phase'] in ('switching', 'verifying'):
                            self.restore_files(Path(self.state['backup']))
                        self.runtime.service('start')
                        self.runtime.health(old)
                    self.publish('rolled_back', error=code)
                    self.release()
                except Exception:
                    self.publish('manual_recovery_required', error='rollback_failed')
                    # Durable maintenance remains; no new control after restart.
                raise UpdateError(code) from None

    def recover(self):
        """Boot-time recovery never starts motors, services, or candidate code."""
        with self.exclusive():
            if self.state['phase'] in TERMINAL:
                if (self.root/'maintenance.json').exists():
                    self.publish('recovered_unverified', error='stale_maintenance_requires_verification')
                return
            self.reserve()
            if self.state['phase'] in ('manual_recovery_required','recovered_unverified'): return
            try:
                previous = self.state.get('previous')
                if not previous or not SHA.fullmatch(previous): raise UpdateError('invalid_recovery_journal')
                phase = self.state['phase']
                switch_link(self.current, self.root/'releases'/previous)
                if phase in ('switching', 'verifying', 'recovered_unverified') and self.state.get('backup'):
                    self.restore_files(Path(self.state['backup']))
                self.publish('recovered_unverified', error='interrupted_update_restored_verify_before_unlock')
            except Exception:
                self.publish('manual_recovery_required', error='boot_recovery_failed')

    def confirm_recovery(self, physical_ack):
        if physical_ack is not True: raise UpdateError('physical_motor_isolation_ack_required')
        with self.exclusive():
            if self.state['phase'] != 'recovered_unverified': raise UpdateError('manual_recovery_required')
            self.runtime.service('start')
            self.runtime.health(self.baseline())
            backup=self.state.get('backup')
            if backup and all((Path(backup)/(name+'-manifest.json')).is_file() for name in self.paths):
                self.check_unchanged(Path(backup))
            self.publish('recovered', error=None)
            self.release()
