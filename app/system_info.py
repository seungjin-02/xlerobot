"""Bounded, read-only diagnostics. Never execute client-supplied commands."""
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path


def output(argv, cwd=None):
    try:
        result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=2,
                                stdin=subprocess.DEVNULL)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def git_version(root):
    commit = output(['git', 'rev-parse', '--verify', 'HEAD^{commit}'], root)
    tag = output(['git', 'describe', '--tags', '--exact-match', 'HEAD'], root)
    dirty = output(['git', 'status', '--porcelain', '--untracked-files=no'], root)
    return {'commit': commit, 'tag': tag, 'modified': None if dirty is None else bool(dirty)}


def storage_info(root):
    path = Path(root).resolve()
    existing = path
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    try:
        usage = shutil.disk_usage(existing)
        return {'path': str(path), 'free_bytes': usage.free, 'total_bytes': usage.total,
                'recording_start_min_bytes': 256 * 1024**2}
    except OSError:
        return {'path': str(path), 'free_bytes': None, 'total_bytes': None}


def service_state(name):
    # systemctl show returns inactive/not-found too, unlike is-active's exit status.
    value = output(['systemctl', '--user', 'show', name, '--property=LoadState',
                    '--property=ActiveState', '--property=SubState'])
    if value is None:
        return {'state': 'unknown'}
    fields = dict(line.split('=', 1) for line in value.splitlines() if '=' in line)
    return {'state': fields.get('ActiveState', 'unknown'),
            'load': fields.get('LoadState', 'unknown'), 'substate': fields.get('SubState', 'unknown')}


class SystemInfo:
    def __init__(self, root, recordings, demo=False):
        self.root, self.recordings, self.demo = Path(root), Path(recordings), demo
        self.updated = 0
        self.cached = {}

    def snapshot(self, control, device_name, fault):
        if time.monotonic() - self.updated > 5 or not self.cached:
            try:
                os_name = platform.freedesktop_os_release().get('PRETTY_NAME')
            except OSError:
                os_name = None
            self.cached = {
                'git': git_version(self.root), 'os': os_name,
                'architecture': platform.machine(),
                'ros': {'sourced_distro': os.environ.get('ROS_DISTRO'),
                        'jazzy_installed': Path('/opt/ros/jazzy/setup.bash').is_file()},
                'services': {name: ({'state': 'not_applicable_demo'} if self.demo else service_state(name))
                             for name in ('lekiwi-phone.service', 'lekiwi-camera.service')},
            }
            self.updated = time.monotonic()
        return {**self.cached, 'device_name': device_name, 'demo': self.demo,
                'web_server': 'responding', 'storage': storage_info(self.recordings),
                'control': control, 'fault': fault,
                'motor': {'feedback_ready': control.get('motor_ready') if control.get('available') else None,
                          'feedback_fresh': bool(control.get('available')),
                          'simulated': self.demo, 'physical_stop_verified': False},
                'base_process': ('simulated' if self.demo else
                                 'running_owned_process' if control.get('base_running') else 'not_owned_or_not_running')}
