#!/usr/bin/env python3
"""Opt-in migration from user units to sandboxed system units. Never run by a release."""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import pwd
import platform
import re
import shutil
import ssl
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'updater'))
from common import SHA, UpdateError, atomic_json, snapshot, switch_link
from engine import Runtime
from releases import Releases
from network import lan_address, verify_certificate_ip


def escape(value):
    value=str(value)
    if any(c in value for c in '\n\r\x00'): raise UpdateError('invalid_unit_path')
    return value.replace('\\','\\\\').replace('"','\\"').replace('%','%%')


def units(user, home, config, recordings, cameras):
    base='/var/lib/lekiwi-updater'
    shared=f'''User={user}
WorkingDirectory={base}/current/app
Environment=ROS_DOMAIN_ID=42 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST LEKIWI_MANAGED_UPDATES=1
Environment=LEKIWI_UPDATE_ROOT={base} PYTHONDONTWRITEBYTECODE=1
Environment="ROS_LOG_DIR={escape(home/'.local/state/lekiwi-phone/ros-log')}"
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=yes
RestrictSUIDSGID=yes
InaccessiblePaths=-/run/user/{pwd.getpwnam(user).pw_uid}/bus -/run/dbus/system_bus_socket -/usr/bin/sudo -/usr/bin/su -/usr/bin/pkexec
InaccessiblePaths="-{escape(home/'.ssh')}" "-{escape(home/'.gnupg')}" "-{escape(home/'.config/systemd')}" "-{escape(home/'.local/share/keyrings')}"
ReadWritePaths="{escape(recordings)}" "{escape(home/'.local/state/lekiwi-phone')}"
KillMode=control-group
TimeoutStopSec=15
Restart=on-failure
RestartSec=3
'''
    phone=f'''[Unit]
Description=LeKiwi managed phone control
Requires=lekiwi-updater.service
After=network.target lekiwi-updater.service
Wants=lekiwi-camera.service
[Service]
{shared}ExecStart={base}/current/start.sh "{escape(config)}"
[Install]
WantedBy=multi-user.target
'''
    specs=' '.join('"'+escape(c['source'])+':'+escape(c['role'])+':'+str(c.get('rotation',0))+'"' for c in cameras)
    camera=f'''[Unit]
Description=LeKiwi managed camera
Requires=lekiwi-updater.service
After=lekiwi-updater.service
[Service]
{shared}ExecStart=/usr/bin/python3 {base}/current/app/camera.py --cams {specs} --port 8080
[Install]
WantedBy=multi-user.target
'''
    daemon='''[Unit]
Description=LeKiwi trusted update executor (SSH tunnel admin)
After=network.target
Before=lekiwi-phone.service lekiwi-camera.service
[Service]
Type=notify
NotifyAccess=main
TimeoutStartSec=600
ExecStart=/usr/bin/python3 /usr/local/lib/lekiwi-updater/daemon.py
UMask=0077
TasksMax=64
MemoryMax=512M
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ReadWritePaths=/var/lib/lekiwi-updater /var/cache/lekiwi-updater
Restart=on-failure
RestartSec=3
[Install]
WantedBy=multi-user.target
'''
    return {'lekiwi-phone.service':phone,'lekiwi-camera.service':camera,'lekiwi-updater.service':daemon}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--robot-user',required=True)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--baseline-commit',required=True)
    parser.add_argument('--signer',action='append',required=True,help='trusted primary GPG fingerprint')
    parser.add_argument('--public-key',type=Path,required=True)
    parser.add_argument('--motor-power-isolated',action='store_true')
    parser.add_argument('--admin-address', help='optional fixed private IPv4 for mobile HTTPS admin')
    parser.add_argument('--tls-cert', type=Path, help='certificate with admin IPv4 in subjectAltName')
    parser.add_argument('--tls-key', type=Path, help='matching private TLS key; copied root-only')
    parser.add_argument('--apply',action='store_true',help='without this, validate and show plan only')
    args=parser.parse_args()
    if not re.fullmatch(r'[a-z_][a-z0-9_-]*',args.robot_user) or not SHA.fullmatch(args.baseline_commit):
        raise SystemExit('Invalid user or baseline commit.')
    mobile = any((args.admin_address, args.tls_cert, args.tls_key))
    if mobile and not all((args.admin_address, args.tls_cert, args.tls_key)):
        raise SystemExit('Mobile admin requires --admin-address, --tls-cert and --tls-key together.')
    address = lan_address(args.admin_address) if mobile else None
    account=pwd.getpwnam(args.robot_user)
    if account.pw_uid==0: raise SystemExit('Robot runtime must not be root.')
    config=args.config.expanduser().resolve()
    data=json.loads(config.read_text())
    home=Path(account.pw_dir)
    paths={'config':config.parent,'recordings':Path(data['recordings']), 'workspace':Path(data['workspace'])}
    for path in paths.values():
        if not path.is_absolute() or path.resolve()!=path or path in (Path('/'),home):
            raise SystemExit('Use resolved dedicated absolute paths without symlinks.')
    if any(a!=b and (a.is_relative_to(b) or b.is_relative_to(a)) for a in paths.values() for b in paths.values()):
        raise SystemExit('Backup roots must not overlap.')
    cameras=data.get('cameras') or [{'source':data['camera'],'role':'front','rotation':data.get('camera_rotation',0)}]
    for cam in cameras:
        if cam['role'] not in ('front','wrist') or not (cam['source'].isdigit() or cam['source'].startswith('/dev/')) or cam.get('rotation',0) not in (0,90,180,270):
            raise SystemExit('Invalid camera configuration.')
    if not (ROOT/'app/maintenance.py').is_file(): raise SystemExit('Baseline must include the update lock gate.')
    plan=units(args.robot_user,home,config,paths['recordings'],cameras)
    print('Plan: root-owned executor, dedicated Git worker, sandboxed system phone/camera units.')
    print('Preserves existing PIN/AP/profile and recordings; changes service ownership and code layout.')
    if address:
        plan['lekiwi-phone.service'] = plan['lekiwi-phone.service'].replace('[Service]\n', '[Service]\nEnvironment=LEKIWI_ADMIN_URL=https://'+address+':8093\n')
        print('Mobile administrator HTTPS:', 'https://'+address+':8093', '(phone must trust the certificate)')
    print('GPG signer count:',len(args.signer),'automatic OS/driver/schema changes: disabled')
    if not args.apply: return
    if os.geteuid()!=0 or not args.motor_power_isolated or not sys.stdin.isatty():
        raise SystemExit('Apply requires root, interactive hidden password input, and physical motor isolation.')
    release=platform.freedesktop_os_release()
    if release.get('ID')!='ubuntu' or release.get('VERSION_ID')!='24.04' or platform.machine()!='aarch64':
        raise SystemExit('Managed deployment requires Ubuntu 24.04 ARM64; this host is unsupported.')
    root=Path('/var/lib/lekiwi-updater');install=Path('/usr/local/lib/lekiwi-updater');settings=Path('/etc/lekiwi-updater')
    if any(p.exists() for p in (root,install,settings)):
        raise SystemExit('Existing managed installation: preserve it and use manual maintenance.')
    if mobile:
        if not shutil.which('openssl'): raise SystemExit('Mobile TLS requires openssl.')
        for path in (args.tls_cert, args.tls_key):
            if path.is_symlink() or not path.is_file(): raise SystemExit('Use regular TLS certificate/key files.')
        if args.tls_key.stat().st_mode & 0o077: raise SystemExit('TLS key must be private (chmod 600).')
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(args.tls_cert, args.tls_key)
        verify_certificate_ip(args.tls_cert, address)
    for program in ('git','gpg','setpriv','systemctl','runuser','useradd'):
        if not shutil.which(program): raise SystemExit('Missing system prerequisite: '+program)
    # Verify the baseline using the robot account; never invoke repo-configured programs as root.
    prefix=['setpriv','--reuid='+str(account.pw_uid),'--regid='+str(account.pw_gid),'--clear-groups','--no-new-privs','--']
    env={**os.environ,'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null','GIT_TERMINAL_PROMPT':'0'}
    def git(*a):
        return subprocess.check_output(prefix+['git','-c','core.hooksPath=/dev/null','-c','core.fsmonitor=false','-C',str(ROOT),*a],env=env).decode().strip()
    if git('rev-parse','HEAD')!=args.baseline_commit or git('status','--porcelain'):
        raise SystemExit('Baseline SHA must match a clean checkout. No reset/stash is performed.')
    Runtime(config).idle()
    password=getpass.getpass('New update administrator password (at least 16 characters): ')
    if len(password)<16 or password!=getpass.getpass('Repeat administrator password: '):
        raise SystemExit('Password confirmation failed.')
    worker='lekiwi-fetch'
    try: fetcher=pwd.getpwnam(worker)
    except KeyError:
        subprocess.run(['useradd','--system','--no-create-home','--home-dir','/var/cache/lekiwi-updater','--shell','/usr/sbin/nologin',worker],check=True)
        fetcher=pwd.getpwnam(worker)
    if fetcher.pw_uid==0: raise SystemExit('Fetch worker must not be root.')
    for name in plan:
        system=Path('/etc/systemd/system')/name
        if system.exists() or system.is_symlink(): raise SystemExit('Existing system unit requires manual review: '+name)
    os.umask(0o077)
    root.mkdir(mode=0o755);root.chmod(0o755);settings.mkdir(mode=0o700)
    backup=root/'bootstrap-backup';backup.mkdir(mode=0o700)
    for name,path in paths.items(): snapshot(path,backup/name)
    user_units=home/'.config/systemd/user'
    for name in plan:
        old=user_units/name
        if old.is_file(): shutil.copy2(old,backup/(name+'.user'))
        system=Path('/etc/systemd/system')/name
        if system.exists() or system.is_symlink(): raise SystemExit('Existing system unit requires manual review: '+name)
    shutil.copytree(ROOT/'updater',install,ignore=shutil.ignore_patterns('__pycache__'))
    for p in install.rglob('*'): p.chmod(0o755 if p.is_dir() else 0o644)
    install.chmod(0o755)
    cache=Path('/var/cache/lekiwi-updater');cache.mkdir(mode=0o700,exist_ok=True);os.chown(cache,fetcher.pw_uid,fetcher.pw_gid)
    keyring=cache/'keys';keyring.mkdir(mode=0o700);os.chown(keyring,fetcher.pw_uid,fetcher.pw_gid)
    key_bytes=args.public_key.read_bytes()
    if not key_bytes.startswith(b'-----BEGIN PGP PUBLIC KEY BLOCK-----') or b'PRIVATE KEY' in key_bytes:
        raise SystemExit('Use an armored public key export only; never provide a private key.')
    subprocess.run(['setpriv','--reuid='+str(fetcher.pw_uid),'--regid='+str(fetcher.pw_gid),'--clear-groups','--no-new-privs','--',
        'gpg','--homedir',str(keyring),'--batch','--import'],input=key_bytes,check=True,capture_output=True)
    listing=subprocess.check_output(['setpriv','--reuid='+str(fetcher.pw_uid),'--regid='+str(fetcher.pw_gid),'--clear-groups','--no-new-privs','--',
        'gpg','--homedir',str(keyring),'--batch','--with-colons','--list-keys'],stderr=subprocess.DEVNULL,text=True)
    imported={line.split(':')[9] for line in listing.splitlines() if line.startswith('fpr:')}
    if not set(args.signer).issubset(imported): raise SystemExit('Pinned signer is not in the imported public key set.')
    source=Releases(cache/'repository.git',keyring,args.signer,fetcher.pw_uid,fetcher.pw_gid)
    source.refresh()
    (root/'releases').mkdir(mode=0o755);(root/'releases').chmod(0o755)
    source.extract(args.baseline_commit,root/'releases'/args.baseline_commit)
    atomic_json(root/'releases'/args.baseline_commit/'.lekiwi-release.json',{'commit':args.baseline_commit},0o644)
    switch_link(root/'current',root/'releases'/args.baseline_commit)
    policy={'root':str(root),'cache':str(source.cache),'keyring':str(keyring),'trusted_fingerprints':args.signer,
        'worker_uid':fetcher.pw_uid,'worker_gid':fetcher.pw_gid,'config_file':str(config),'snapshot_paths':{k:str(v) for k,v in paths.items()}}
    if mobile:
        policy['admin_address'] = address
        for tls_source, name in ((args.tls_cert, 'admin-cert.pem'), (args.tls_key, 'admin-key.pem')):
            target = settings/name
            target.write_bytes(tls_source.read_bytes()); target.chmod(0o600)
    atomic_json(settings/'policy.json',policy)
    salt=os.urandom(16)
    atomic_json(settings/'admin.json',{'salt':salt.hex(),'hash':hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1).hex()})
    for path in (paths['recordings'],home/'.local/state/lekiwi-phone'):
        if not path.exists(): path.mkdir(parents=True,mode=0o700);os.chown(path,account.pw_uid,account.pw_gid)
    # Runtime writes are limited to existing mutable locations; updater may restore them on failure.
    daemon=plan['lekiwi-updater.service']
    daemon=daemon.replace('ReadWritePaths=/var/lib/lekiwi-updater /var/cache/lekiwi-updater',
        'ReadWritePaths=/var/lib/lekiwi-updater /var/cache/lekiwi-updater '+' '.join('"'+escape(p)+'"' for p in paths.values()))
    plan['lekiwi-updater.service']=daemon
    for name,content in plan.items():
        target=Path('/etc/systemd/system')/name;target.write_text(content);target.chmod(0o644)
    # Old services are preserved; no AP changes and no removal of old source/workspace.
    user_env={**os.environ,'XDG_RUNTIME_DIR':'/run/user/'+str(account.pw_uid),
        'DBUS_SESSION_BUS_ADDRESS':'unix:path=/run/user/'+str(account.pw_uid)+'/bus'}
    user_systemctl=['runuser','-u',args.robot_user,'--','systemctl','--user']
    previous={}
    for name in ('lekiwi-phone.service','lekiwi-camera.service'):
        previous[name]={verb:subprocess.run(user_systemctl+[verb,name],env=user_env,capture_output=True,text=True).stdout.strip()
            for verb in ('is-active','is-enabled')}
    atomic_json(backup/'previous-user-services.json',previous)
    try:
        subprocess.run(user_systemctl+['disable','--now',*previous],env=user_env,check=True)
        subprocess.run(['systemctl','daemon-reload'],check=True)
        subprocess.run(['systemctl','enable','--now',*plan],check=True)
        Runtime(config).health(args.baseline_commit)
    except Exception:
        subprocess.run(['systemctl','disable','--now',*plan],capture_output=True)
        for name,state in previous.items():
            if state['is-enabled'] in ('enabled','enabled-runtime'):
                flags=['--runtime'] if state['is-enabled']=='enabled-runtime' else []
                subprocess.run(user_systemctl+['enable',*flags,name],env=user_env,capture_output=True)
            if state['is-active']=='active': subprocess.run(user_systemctl+['start',name],env=user_env,capture_output=True)
        raise SystemExit('Managed verification failed. Previous user service restoration attempted; inspect both scopes and preserved bootstrap-backup.')
    print('Managed services responded. Physical motion/reboot/rollback remain separate field tests.')

if __name__=='__main__': main()
