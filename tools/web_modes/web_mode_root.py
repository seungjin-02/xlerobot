#!/usr/bin/python3 -I
"""Fixed-command root helper. Never arms motors or sends motion commands."""
import fcntl
import http.cookiejar
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
from web_mode_policy import MODES, require_idle

HOME = Path('/home/roboseasy')
STATE = Path('/var/lib/xlerobot-web-mode')
CUSTOM = ('lekiwi-phone.service', 'lekiwi-camera.service', 'lekiwi-lidar.service')
FACTORY = 'lekiwi-web-operator.service'
USERCTL = ['runuser', '-u', 'roboseasy', '--', 'env', 'XDG_RUNTIME_DIR=/run/user/1000',
           'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus', 'systemctl', '--user']


def command(args, check=True):
    return subprocess.run(args, check=check, capture_output=True, text=True, timeout=65)


def active(unit, user=False):
    result = command((USERCTL if user else ['systemctl']) + ['show', '-p', 'ActiveState', '--value', unit])
    return result.stdout.strip() not in ('inactive', 'failed')


def shared_engine():
    return (STATE/'shared-native').is_file()


def idle(mode, data):
    return require_idle('factory' if shared_engine() else mode, data)


def status():
    custom = {u: active(u, True) for u in CUSTOM}
    factory = active(FACTORY)
    if shared_engine():
        legacy = any(custom[u] for u in CUSTOM if u != 'lekiwi-phone.service')
        phone = custom['lekiwi-phone.service']
        mode = 'conflict' if legacy or (phone and not factory) else 'custom' if phone else 'factory' if factory else 'off'
    else:
        mode = 'conflict' if factory and any(custom.values()) else 'factory' if factory else 'custom' if any(custom.values()) else 'off'
    saved = json.loads((STATE/'state.json').read_text()) if (STATE/'state.json').exists() else {}
    return {'mode': mode, 'custom_units': custom, 'factory_active': factory, 'saved_mode': saved.get('mode')}


def api_status(mode):
    port = 8090 if mode == 'custom' and not shared_engine() else 8080
    base = 'http://127.0.0.1:' + str(port)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    if mode == 'custom' and not shared_engine():
        pin = json.loads((HOME/'.config/lekiwi-phone/config.json').read_text())['pin']
        req = urllib.request.Request(base+'/api/pair', data=json.dumps({'pin': pin}).encode(),
            headers={'Content-Type': 'application/json', 'Origin': base})
        with opener.open(req, timeout=4):
            pass
    with opener.open(base+'/api/status', timeout=5) as response:
        return json.load(response)


def serial_holders(allowed_custom=False):
    targets = set()
    for name in ('lekiwi_motor', 'lekiwi_arm_left', 'lekiwi_arm_right', 'ydlidar'):
        p = Path('/dev')/name
        if p.exists():
            targets.add(str(p.resolve()))
    found = []
    for process in Path('/proc').glob('[0-9]*'):
        try:
            group = (process/'cgroup').read_text()
            allowed = allowed_custom and any('/'+u in group for u in CUSTOM)
            for fd in (process/'fd').iterdir():
                if os.readlink(fd) in targets and not allowed:
                    found.append(int(process.name))
                    break
        except (FileNotFoundError, ProcessLookupError):
            continue
    return sorted(set(found))


def stop_all():
    command(USERCTL + ['stop', *CUSTOM])
    command(['systemctl', 'stop', FACTORY])
    current = status()
    if current['mode'] != 'off':
        raise RuntimeError('이전 서비스가 종료되지 않았습니다')
    holders = serial_holders()
    if holders:
        raise RuntimeError('다른 프로그램이 직렬 장치를 사용 중입니다: ' + str(holders))


def require_target_devices(mode):
    # The factory gateway may stay available for diagnosis without bringup.
    # Custom mode starts the sensor services, so never start it with a known
    # disconnected motor/LiDAR bus or repeatedly restart that failed hardware.
    if mode == 'custom' and not shared_engine():
        missing = [p for p in ('/dev/lekiwi_motor', '/dev/ydlidar') if not Path(p).exists()]
        if missing:
            raise ValueError('바퀴·LiDAR USB 연결이 끊겨 전환을 중단했습니다. '
                             '전원을 끄고 USB 허브·전원·케이블을 점검하세요: ' + ', '.join(missing))


def start_mode(mode):
    require_target_devices(mode)
    if mode == 'custom' and shared_engine():
        command(['systemctl', 'start', FACTORY])
        command(USERCTL + ['start', 'lekiwi-phone.service'])
    elif mode == 'custom':
        command(USERCTL + ['start', 'lekiwi-camera.service', 'lekiwi-lidar.service', 'lekiwi-phone.service'])
    else:
        command(['systemctl', 'start', FACTORY])
    deadline = time.monotonic()+25
    while time.monotonic() < deadline:
        try:
            idle(mode, api_status(mode))
            if mode == 'custom' and shared_engine():
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open('http://127.0.0.1:8090/health',timeout=3) as response:
                    health=json.load(response)
                if health.get('backend') != 'native':raise ValueError('Mobile backend not ready')
            current = status()
            if current['mode'] == mode and (mode != 'custom' or (shared_engine() and current['custom_units']['lekiwi-phone.service']) or all(current['custom_units'].values())):
                return
        except Exception:
            pass
        time.sleep(.4)
    raise RuntimeError('선택한 웹앱의 대기 상태를 확인하지 못했습니다')


def switch(mode, boot=False):
    if mode not in MODES:
        raise ValueError('Unknown controller')
    require_target_devices(mode)
    before = status()
    if before['mode'] == 'conflict':
        raise ValueError('두 서비스가 함께 실행 중입니다. 자동 전환을 거부합니다')
    previous = before['mode']
    if previous in MODES:
        idle(previous, api_status(previous))
    holders = serial_holders(allowed_custom=previous == 'custom')
    if holders:
        raise ValueError('기존 로봇 기능 또는 별도 프로그램을 먼저 종료하세요: '+str(holders))
    try:
        stop_all()
        start_mode(mode)
    except Exception:
        # The previous controller resumes idle only; no motor/session state is restored.
        stop_all()
        if previous in MODES:
            start_mode(previous)
        raise
    temp = STATE/'state.tmp'
    temp.write_text(json.dumps({'mode': mode, 'changed_at': time.time()}))
    temp.chmod(0o600)
    temp.replace(STATE/'state.json')
    return status()


def main():
    if os.geteuid() != 0:
        raise PermissionError('root helper required')
    args = sys.argv[1:]
    if args == ['status']:
        return status()
    if len(args) == 2 and args[0] == 'assert' and args[1] in MODES:
        current = status()
        if shared_engine():
            opposite = any(current['custom_units'][u] for u in CUSTOM if u != 'lekiwi-phone.service')
        else:
            opposite = current['factory_active'] if args[1] == 'custom' else any(current['custom_units'].values())
        if opposite:
            raise ValueError('다른 웹 조작기가 실행 중입니다. 전환 화면을 사용하세요')
        return {'ok': True}
    if args != ['boot'] and not (len(args) == 2 and args[0] == 'switch' and args[1] in MODES):
        raise ValueError('Unknown action')
    STATE.mkdir(mode=0o700, exist_ok=True)
    with (STATE/'operation.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args == ['boot']:
            mode = json.loads((STATE/'state.json').read_text())['mode']
        else:
            mode = args[1]
        return switch(mode, boot=args == ['boot'])


if __name__ == '__main__':
    try:
        print(json.dumps(main(), ensure_ascii=False))
    except Exception as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False))
        sys.exit(1)
