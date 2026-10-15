"""Fixed update protocol and durable, private filesystem operations."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

REPOSITORY = 'https://github.com/seungjin-02/xlerobot.git'
TAG = re.compile(r'v[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?\Z')
SHA = re.compile(r'[0-9a-f]{40}\Z')
TERMINAL = {'idle', 'succeeded', 'rolled_back', 'recovered'}

class UpdateError(Exception):
    pass


def valid_admin_password(value):
    return isinstance(value, str) and (16 <= len(value) <= 256 or
        len(value) == 6 and value.isascii() and value.isdecimal())


def atomic_json(path, value, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.update-', dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'w') as f:
            json.dump(value, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if os.path.exists(name): os.unlink(name)


def manifest(root, links_root=None):
    root = Path(root)
    if not root.exists(): return {'exists': False, 'files': {}, 'bytes': 0}
    if root.is_symlink() or not root.is_dir(): raise UpdateError('backup_path_invalid')
    files = {}
    directories = {}
    def metadata(path):
        value=path.lstat()
        return {'uid':value.st_uid,'gid':value.st_gid,'mode':value.st_mode & 0o7777}
    root_stat=metadata(root)
    for p in sorted(root.rglob('*')):
        if p.is_symlink():
            # Relative links resolve inside the copied tree; absolute links may still
            # refer to the original workspace. Both must remain within verified roots.
            allowed = (root.resolve(), Path(links_root or root).resolve())
            if not any(p.resolve().is_relative_to(base) for base in allowed):
                raise UpdateError('external_links_require_manual_backup')
            files[str(p.relative_to(root))] = {'bytes': 0, 'link': os.readlink(p), **metadata(p)}
            continue
        if p.is_dir():
            directories[str(p.relative_to(root))]=metadata(p)
            continue
        if not p.is_file(): raise UpdateError('special_files_require_manual_backup')
        h = hashlib.sha256()
        with p.open('rb') as f:
            for block in iter(lambda: f.read(1024 * 1024), b''): h.update(block)
        files[str(p.relative_to(root))] = {'bytes': p.stat().st_size, 'sha256': h.hexdigest(), **metadata(p)}
    return {'exists': True, 'root_stat':root_stat, 'directories':directories, 'files': files, 'bytes': sum(f['bytes'] for f in files.values())}


def preserve_ownership(source, target):
    if os.geteuid()!=0: return
    source,target=Path(source),Path(target)
    for p in [source,*source.rglob('*')]:
        value=p.lstat()
        os.chown(target/p.relative_to(source),value.st_uid,value.st_gid,follow_symlinks=False)


def snapshot(source, target):
    source, target = Path(source), Path(target)
    before = manifest(source)
    if before['exists']:
        shutil.copytree(source, target, symlinks=True)
        preserve_ownership(source,target)
    if manifest(target, links_root=source) != before or manifest(source) != before:
        raise UpdateError('backup_verification_failed')
    return before


def switch_link(link, target):
    link, target = Path(link), Path(target)
    temp = link.with_name('.current-next')
    if temp.is_symlink(): temp.unlink()
    if temp.exists(): raise UpdateError('unexpected_switch_file')
    temp.symlink_to(target, target_is_directory=True)
    os.replace(temp, link)
    fd = os.open(link.parent, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)
