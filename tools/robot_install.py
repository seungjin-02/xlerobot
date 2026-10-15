#!/usr/bin/env python3
"""Trusted SSH-side installer implementation, invoked by install_assistant.py.

Only initial installs. No network reconfiguration, update API, or motor commands.
All subprocess arguments are fixed commands plus validated data, never shell=True.
"""
import base64
import getpass
import io
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPOSITORY = 'https://github.com/seungjin-02/xlerobot.git'
APP_URL = 'http://192.168.4.1:8090'
SERVICES = ('lekiwi-phone.service', 'lekiwi-camera.service')


class InstallError(RuntimeError):
    pass


class CommandError(InstallError):
    def __init__(self, program, code):
        super().__init__(f'{program}: 실패 (종료 코드 {code})')
        self.code = code


def run(argv, cwd=None, timeout=60):
    env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0'}
    try:
        result = subprocess.run(argv, cwd=cwd, env=env, capture_output=True,
                                text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        raise InstallError(f'{Path(argv[0]).name}: 실행 불가 또는 시간 초과') from None
    if result.returncode:
        # Do not echo stderr, which may contain private credential-helper output.
        raise CommandError(Path(argv[0]).name, result.returncode)
    return result.stdout.strip()


def validate_release(tag, commit):
    if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?', tag):
        raise InstallError('릴리스 태그는 vX.Y.Z 또는 vX.Y.Z-사전릴리스 형식이어야 합니다')
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise InstallError('관리자가 검증한 전체 40자리 Git 커밋이 필요합니다')


def target_path(directory):
    home = Path.home().resolve()
    relative = Path(directory)
    if relative.is_absolute() or not relative.parts or any(p in ('.', '..') or p.startswith('.') for p in relative.parts):
        raise InstallError('설치 경로는 홈 아래의 숨김이 아닌 상대 경로여야 합니다')
    path = (home / relative).resolve()
    if path == home or not path.is_relative_to(home):
        raise InstallError('홈 밖에는 설치할 수 없습니다')
    return path


def resolve_tag(tag):
    try:
        text = run(['git', 'ls-remote', '--exit-code', '--tags', REPOSITORY,
                    'refs/tags/' + tag, 'refs/tags/' + tag + '^{}'])
    except CommandError as error:
        if error.code == 2:
            raise InstallError('선택한 릴리스 태그가 없습니다. 관리자의 검증 릴리스를 확인하세요') from None
        raise InstallError('GitHub Git 읽기 실패. Pi의 인증·DNS·HTTPS 접근을 확인하세요') from None
    refs = dict((ref, sha) for sha, ref in (line.split() for line in text.splitlines()))
    return refs.get('refs/tags/' + tag + '^{}') or refs.get('refs/tags/' + tag)


def inspect(request):
    validate_release(request['tag'], request['commit'])
    target = target_path(request['directory'])
    if target.exists() or target.is_symlink() or (Path.home()/'.config/lekiwi-phone/config.json').exists():
        raise InstallError('기존 설치/경로가 있습니다. 덮어쓰지 않습니다. docs/UPDATE.md의 수동 업데이트를 사용하세요')
    if os.geteuid() == 0:
        raise InstallError('root 대신 로봇 일반 사용자로 SSH 접속하세요')
    release = platform.freedesktop_os_release()
    if release.get('ID') != 'ubuntu' or release.get('VERSION_ID') != '24.04' or platform.machine() != 'aarch64':
        raise InstallError('대상은 Raspberry Pi Ubuntu 24.04 ARM64(aarch64)여야 합니다')
    for program in ('git', 'ip', 'sudo', 'systemctl', 'bash'):
        if not shutil.which(program):
            raise InstallError(program + ' 미설치: Raspberry Pi에서 먼저 설치하세요')
    try:
        import yaml  # existing setup_robot prerequisite, installed before running the helper
    except ImportError:
        raise InstallError('Pi에 python3-yaml이 필요합니다: sudo apt-get install python3-yaml') from None
    routes = json.loads(run(['ip', '-j', 'route', 'show', 'default']))
    if not routes:
        raise InstallError('기본 게이트웨이가 없습니다. 인터넷 공유/공유기 연결을 확인하세요')
    try:
        socket.getaddrinfo('github.com', 443)
    except OSError:
        raise InstallError('GitHub DNS 해석 실패') from None
    if resolve_tag(request['tag']) != request['commit']:
        raise InstallError('릴리스 태그와 검증된 예상 커밋이 일치하지 않습니다')
    # Git HTTPS read above also tests Pi-side private repository authentication.
    destinations = (
        'https://ports.ubuntu.com/ubuntu-ports/dists/noble/Release',
        'https://api.github.com/repos/ros-infrastructure/ros-apt-source/releases/latest',
    )
    for url in destinations:
        try:
            with urllib.request.urlopen(url, timeout=15) as response:
                if response.status != 200:
                    raise InstallError('Ubuntu/ROS 의존성 네트워크 접근 실패')
        except OSError:
            raise InstallError('Ubuntu/ROS 의존성 네트워크 접근 실패 (TLS/프록시/방화벽 확인)') from None
    return {'os': release['PRETTY_NAME'], 'architecture': platform.machine(),
            'git': run(['git', '--version']), 'tag': request['tag'], 'commit': request['commit'],
            'ros_jazzy_installed': Path('/opt/ros/jazzy/setup.bash').exists(),
            'network': 'gateway, DNS, Git HTTPS and Ubuntu/ROS bootstrap endpoints passed',
            'destination': str(target), 'existing_installation': False}


def clone_release(request):
    target = target_path(request['directory'])
    if target.exists() or target.is_symlink():
        raise InstallError('대상 경로가 이미 있습니다. 자동 삭제/초기화하지 않습니다')
    target.parent.mkdir(parents=True, exist_ok=True)
    run(['git', 'clone', '--no-checkout', '--', REPOSITORY, str(target)], timeout=300)
    actual = run(['git', 'rev-parse', '--verify', 'refs/tags/' + request['tag'] + '^{commit}'], target)
    if actual != request['commit']:
        raise InstallError('clone 이후 태그 커밋 불일치. 설치하지 않고 체크아웃을 보존합니다')
    run(['git', 'checkout', '--detach', actual], target)
    return target


def verify_services():
    for name in SERVICES:
        if run(['systemctl', '--user', 'is-active', name]) != 'active':
            raise InstallError(name + ' 시작 실패')
    # No pairing or arm request: health plus fresh camera JPEG only.
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with client.open('http://127.0.0.1:8090/health', timeout=5) as response:
        if json.load(response) != {'ok': True, 'demo': False}:
            raise InstallError('실물 웹 서버 health 확인 실패')
    with client.open('http://127.0.0.1:8080/snapshot', timeout=5) as response:
        frame = response.read(2_000_001)
        if not frame.startswith(b'\xff\xd8') or not frame.endswith(b'\xff\xd9') or len(frame) > 2_000_000:
            raise InstallError('본체 카메라 JPEG 확인 실패')


def completion(target, request, write_version=False):
    verify_services()
    commit = run(['git', 'rev-parse', 'HEAD'], target)
    if commit != request['commit']:
        raise InstallError('설치 후 커밋이 변경됐습니다')
    config_dir = Path.home()/'.config/lekiwi-phone'
    config = json.loads((config_dir/'config.json').read_text())
    version = {'repository': REPOSITORY, 'tag': request['tag'], 'commit': commit,
               'verified_at_unix': time.time(), 'physical_motion_tested': False}
    version_path = config_dir/'installed-version.json'
    if write_version:
        descriptor = os.open(version_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as destination:
            json.dump(version, destination, indent=2)
    else:
        installed = json.loads(version_path.read_text())
        if installed.get('tag') != request['tag'] or installed.get('commit') != commit:
            raise InstallError('설치 완료 버전 기록 불일치')
    result = {'success': True, 'device_name': config.get('name'), 'ssid': config.get('ssid'),
              'tag': request['tag'], 'commit': commit, 'url': APP_URL, 'services': 'verified',
              'reboot_required': True, 'physical_motion_tested': False, 'qr_svg_base64': None}
    try:
        import qrcode
        import qrcode.image.svg
        stream = io.BytesIO()
        qrcode.make(APP_URL, image_factory=qrcode.image.svg.SvgPathImage).save(stream)
        result['qr_svg_base64'] = base64.b64encode(stream.getvalue()).decode('ascii')
    except (ImportError, OSError):
        pass  # Manual URL remains usable. Never include PIN or Wi-Fi password.
    return result


def install(request):
    if not sys.stdin.isatty():
        raise InstallError('비표시 PIN/sudo 입력을 위한 SSH TTY가 필요합니다')
    print('[1/5] 대상·네트워크·릴리스 재검사', flush=True)
    inspect(request)
    if request.get('confirm_wheel_map') is not True:
        raise InstallError('기기별 바퀴 순서·방향·치수 확인이 필요합니다')
    print('[2/5] Git clone 및 태그 커밋 검증', flush=True)
    target = clone_release(request)
    import yaml
    sys.path.insert(0, str(target))
    from setup_robot import validate_profile
    content = base64.b64decode(request['profile_base64'], validate=True)
    if len(content) > 16 * 1024:
        raise InstallError('프로필이 너무 큽니다')
    profile = yaml.safe_load(content)
    validate_profile(profile)
    serial = request['serial_port']
    if not serial.startswith('/dev/') or not Path(serial).is_char_device():
        raise InstallError('지정한 모터 시리얼 장치가 없습니다')
    print('[3/5] 프로필 검사 및 기존 install.sh 실행 (sudo는 SSH 터미널에서 인증)', flush=True)
    with tempfile.TemporaryDirectory(prefix='lekiwi-install-') as temporary:
        profile_path = Path(temporary)/'robot-profile.yaml'
        profile_path.write_bytes(content); profile_path.chmod(0o600)
        pin = getpass.getpass('새 웹앱 PIN (4~8자리 숫자, 화면/로그에 표시하지 않음): ')
        if not re.fullmatch(r'[0-9]{4,8}', pin):
            raise InstallError('PIN 형식 오류')
        pin_path = Path(temporary)/'pin'
        pin_path.write_text(pin); pin_path.chmod(0o600)
        arguments = ['bash', 'install.sh', '--profile', str(profile_path), '--serial-port', serial,
                     '--noninteractive', '--confirm-wheel-map', '--camera', request['camera'], '--pin-file', str(pin_path)]
        if request.get('wrist_camera'):
            arguments += ['--has-arm', '--wrist-camera', request['wrist_camera']]
        # No --activate-ap: never intentionally interrupt this SSH network.
        code = subprocess.call(arguments, cwd=target)
        if code:
            raise InstallError(f'install.sh 실패 ({code}). 체크아웃과 설정을 보존합니다. 자동 재시도하지 마세요')
    print('[4/5] 서비스·웹·본체 카메라 확인', flush=True)
    for attempt in range(10):
        try:
            verify_services()
            break
        except (InstallError, OSError, ValueError):
            if attempt == 9:
                raise InstallError('서비스 검증 실패. journalctl, 그룹 권한/재부팅 및 카메라를 확인하세요') from None
            time.sleep(1)
    print('[5/5] 버전 기록 및 연결 안내 생성', flush=True)
    return completion(target, request, write_version=True)


def main(request):
    try:
        validate_release(request['tag'], request['commit'])
        if request['action'] == 'check':
            result = inspect(request)
        elif request['action'] == 'install':
            result = install(request)
            result.pop('qr_svg_base64', None)
        elif request['action'] == 'result':
            result = completion(target_path(request['directory']), request)
        else:
            raise InstallError('지원하지 않는 설치 작업')
        # Unique marker lets the PC ignore interactive sudo/build output.
        print('LEKIWI_RESULT=' + json.dumps(result, ensure_ascii=True), flush=True)
        return 0
    except (InstallError, OSError, ValueError, KeyError) as error:
        if isinstance(error, InstallError):
            print('LeKiwi: ' + str(error), file=sys.stderr)
        else:
            print('LeKiwi: 설치/검증 실패. 기기 로그와 설치 문서를 확인하세요. 자동 초기화하지 않습니다.', file=sys.stderr)
        return 1
