"""Fetch as an unprivileged worker; authenticate annotated Git tags."""
import io
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tarfile

from common import REPOSITORY, TAG, SHA, UpdateError

# No root execution of install.sh, setup_robot.py or any candidate code.
ALLOWED = ('app/', 'docs/', 'site/', 'tests/', 'evidence/', '.github/')
ALLOWED_FILES = {'README.md', 'LICENSE-NOTICE.md'}

class Releases:
    def __init__(self, cache, keys, fingerprints, uid, gid):
        self.cache, self.keys = Path(cache), Path(keys)
        self.fingerprints = set(fingerprints)
        self.uid, self.gid = uid, gid
        if not self.fingerprints or any(len(f) not in (40, 64) or any(c not in '0123456789ABCDEF' for c in f) for f in self.fingerprints):
            raise UpdateError('trusted_signer_required')

    def run(self, args, binary=False):
        prefix = []
        if os.geteuid() == 0:
            prefix = ['setpriv', '--reuid='+str(self.uid), '--regid='+str(self.gid), '--clear-groups', '--no-new-privs', '--']
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(self.cache.parent), 'LANG': 'C.UTF-8',
               'GNUPGHOME': str(self.keys), 'GIT_CONFIG_NOSYSTEM': '1',
               'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_TERMINAL_PROMPT': '0'}
        try:
            r = subprocess.run(prefix + ['git', '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
                '-c', 'protocol.file.allow=never', '-c', 'gpg.format=openpgp', '-c', 'gpg.program=/usr/bin/gpg', *args], env=env, stdin=subprocess.DEVNULL,
                capture_output=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired): raise UpdateError('git_unavailable_or_timeout') from None
        if r.returncode: raise UpdateError('git_or_signature_check_failed')
        if 'verify-tag' in args: return (r.stdout + r.stderr).decode().strip()
        return r.stdout if binary else r.stdout.decode().strip()

    def refresh(self):
        if not self.cache.exists():
            self.run(['clone', '--bare', '--', REPOSITORY, str(self.cache)])
        if self.run(['-C', str(self.cache), 'config', '--get-all', 'remote.origin.url']) != REPOSITORY:
            raise UpdateError('repository_origin_mismatch')
        # No forced tag replacement: moved/colliding tags fail closed.
        self.run(['-C', str(self.cache), 'fetch', '--prune', 'origin', '+refs/heads/main:refs/heads/main', 'refs/tags/*:refs/tags/*'])

    def git(self, *args, binary=False):
        return self.run(['-C', str(self.cache), *args], binary=binary)

    def describe(self, tag, baseline):
        if not isinstance(tag, str) or not TAG.fullmatch(tag): raise UpdateError('invalid_release_tag')
        if not SHA.fullmatch(baseline): raise UpdateError('invalid_baseline')
        if self.git('cat-file', '-t', 'refs/tags/'+tag) != 'tag': raise UpdateError('signed_annotated_tag_required')
        # --raw machine status is captured privately; trust explicit fingerprints only.
        raw = self.git('verify-tag', '--raw', tag)
        signers = {line.split()[2] for line in raw.splitlines() if line.startswith('[GNUPG:] VALIDSIG ')}
        primaries = {line.split()[-1] for line in raw.splitlines() if line.startswith('[GNUPG:] VALIDSIG ')}
        if not (signers | primaries) & self.fingerprints: raise UpdateError('untrusted_release_signer')
        sha = self.git('rev-parse', 'refs/tags/'+tag+'^{commit}')
        self.git('merge-base', '--is-ancestor', sha, 'refs/heads/main')
        # Downgrades use journal rollback, not a remote old-tag installation.
        self.git('merge-base', '--is-ancestor', baseline, sha)
        meta = json.loads(self.git('show', sha+':update-release.json'))
        if (not isinstance(meta,dict) or meta.get('schema') != 1 or meta.get('kind') != 'application' or
                meta.get('qualified') is not True or meta.get('config_schema') != 1 or
                meta.get('recording_schema') != 'lekiwi-episode-v1' or
                meta.get('platform') != 'ubuntu-24.04-aarch64' or meta.get('updater_protocol') != 1):
            raise UpdateError('release_requires_manual_migration')
        paths = self.git('diff', '--name-only', baseline, sha).splitlines()
        if any(p != 'update-release.json' and p not in ALLOWED_FILES and not p.startswith(ALLOWED) for p in paths):
            raise UpdateError('dependency_driver_or_installer_change_requires_manual_update')
        return {'tag': tag, 'commit': sha, 'notes': str(meta.get('notes', ''))[:8000],
                'changes': paths[:200], 'qualified_by_trusted_signer': True}

    def list(self, baseline):
        self.refresh()
        result = []
        for tag in self.git('tag', '--sort=-version:refname').splitlines()[:30]:
            if not TAG.fullmatch(tag): continue
            try:
                release=self.describe(tag, baseline)
                if release['commit']!=baseline: result.append(release)
            except (UpdateError, ValueError, TypeError): continue
        return result

    def extract(self, sha, destination):
        if not SHA.fullmatch(sha): raise UpdateError('invalid_release_commit')
        data = self.git('archive', '--format=tar', sha, binary=True)
        if len(data) > 100 * 1024**2: raise UpdateError('release_too_large')
        destination = Path(destination)
        if destination.exists(): raise UpdateError('release_destination_exists')
        destination.mkdir(mode=0o755)
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            members = archive.getmembers()
            if sum(m.size for m in members) > 200 * 1024**2: raise UpdateError('release_too_large')
            for member in members:
                path = PurePosixPath(member.name)
                if path.is_absolute() or '..' in path.parts or not (member.isfile() or member.isdir()):
                    raise UpdateError('unsafe_release_archive')
                target = destination / member.name
                if member.isdir(): target.mkdir(parents=True, exist_ok=True, mode=0o755)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
                    with archive.extractfile(member) as source: target.write_bytes(source.read())
                    target.chmod(0o755 if member.mode & 0o111 else 0o644)
        for directory in destination.rglob('*'):
            if directory.is_dir(): directory.chmod(0o755)
        destination.chmod(0o755)
        # Runtime version is read independently of the original checkout.
        (destination / '.lekiwi-release.json').write_text(json.dumps({'commit': sha}))
