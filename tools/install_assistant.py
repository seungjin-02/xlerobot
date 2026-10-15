#!/usr/bin/env python3
"""PC CLI: explicit release + hardware profile, system OpenSSH authentication.

CLI and simulated SSH tests run on Linux/Python 3.12. Full Raspberry Pi
installation and Windows/macOS execution have not yet been validated.
"""
import argparse
import base64
import html
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from robot_install import APP_URL, InstallError, validate_release


def ssh_command(host, port, request, interactive=False):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', host):
        raise InstallError('--host는 사용자@IPv4주소 또는 사용자@호스트명 형식이어야 합니다')
    if not 1 <= port <= 65535:
        raise InstallError('SSH 포트는 1~65535여야 합니다')
    source = Path(__file__).with_name('robot_install.py').read_text()
    payload = base64.b64encode(json.dumps(request).encode()).decode('ascii')
    program = (source + '\nraise SystemExit(main(json.loads(base64.b64decode(' + repr(payload) + '))))\n')
    command = shlex.join(['python3', '-c', program])
    return ['ssh', '-t' if interactive else '-T', '-p', str(port),
            '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=15',
            '-o', 'ServerAliveCountMax=2', '-o', 'StrictHostKeyChecking=ask', host, command]


def result_from(text):
    for line in reversed(text.splitlines()):
        if line.startswith('LEKIWI_RESULT='):
            return json.loads(line[len('LEKIWI_RESULT='):])
    raise InstallError('설치 결과를 받지 못했습니다. 설치 완료로 간주하지 않습니다')


def write_completion(path, result):
    if result.get('success') is not True or result.get('url') != APP_URL:
        raise InstallError('확인된 설치 완료 결과가 아닙니다')
    esc = lambda value: html.escape(str(value or '확인 불가'), quote=True)
    qr = ''
    if result.get('qr_svg_base64'):
        encoded = result['qr_svg_base64']
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except ValueError:
            decoded = b''
        if 0 < len(decoded) <= 128 * 1024:
            qr = '<img width="240" height="240" alt="웹앱 주소 QR" src="data:image/svg+xml;base64,' + encoded + '">'
    body = f'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'">
<title>LeKiwi 설치 완료</title><style>body{{font:16px system-ui;max-width:720px;margin:40px auto;padding:24px;line-height:1.7}}code{{overflow-wrap:anywhere}}</style>
<h1>LeKiwi Control Center 설치 완료</h1><p>장치: {esc(result.get('device_name'))}</p>
<p>릴리스 {esc(result.get('tag'))} · <code>{esc(result.get('commit'))}</code></p><p>웹·카메라 서비스 응답 확인. 실물 주행은 검증하지 않았습니다.</p>
<h2>스마트폰 연결</h2><ol><li>최초 설치 후 Raspberry Pi를 재부팅합니다.</li><li>스마트폰 Wi-Fi 설정에서 <strong>{esc(result.get('ssid'))}</strong> AP에 연결합니다. 암호는 기기 관리자에게 확인하세요.</li>
<li>웹앱 주소 QR을 스캔하거나 아래 주소를 입력합니다. 이 QR은 Wi-Fi 연결 QR이 아닙니다.</li><li>별도로 설정한 PIN으로 인증합니다.</li></ol>
{qr}<p>수동 주소: <a href="{APP_URL}">{APP_URL}</a></p><p>PIN·인증 토큰·Wi-Fi 암호는 이 파일과 URL QR에 포함되지 않습니다.</p>
<p>AP가 나타나지 않으면 자동으로 네트워크를 바꾸지 말고 docs/TROUBLESHOOTING.md를 확인하세요. 최초 방향·정지 확인은 현장에서 1배로 수행하세요.</p></html>'''
    path = Path(path)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, 'w') as destination:
        destination.write(body)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True, help='robot-user@IP (SSH 키/agent 또는 터미널 인증)')
    parser.add_argument('--port', type=int, default=22)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--commit', required=True, help='관리자가 별도 검증한 태그의 40자리 커밋')
    parser.add_argument('--directory', default='xlerobot', help='Pi 홈 아래 새 설치 경로')
    parser.add_argument('--install', action='store_true', help='생략하면 읽기 전용 사전 검사만 실행')
    parser.add_argument('--profile', type=Path)
    parser.add_argument('--serial-port')
    parser.add_argument('--camera', default='0')
    parser.add_argument('--wrist-camera')
    parser.add_argument('--confirm-wheel-map', action='store_true')
    parser.add_argument('--output', type=Path, default=Path('lekiwi-installed.html'))
    args = parser.parse_args(argv)
    try:
        validate_release(args.tag, args.commit)
        if not shutil.which('ssh'):
            raise InstallError('PC에 OpenSSH 클라이언트가 필요합니다')
        request = {'action': 'check', 'tag': args.tag, 'commit': args.commit, 'directory': args.directory}
        profile_content = None
        if args.install:
            if not sys.stdin.isatty():
                raise InstallError('설치는 SSH/sudo/PIN 비표시 입력이 가능한 대화형 PC 터미널에서 실행하세요')
            if not args.profile or not args.serial_port or not args.confirm_wheel_map:
                raise InstallError('--profile, --serial-port, --confirm-wheel-map을 명시하세요')
            if args.output.exists():
                raise InstallError('완료 안내 파일이 이미 있습니다. 새 --output 경로를 지정하세요')
            if not args.output.parent.is_dir():
                raise InstallError('--output의 상위 폴더가 없습니다. PC에서 먼저 준비하세요')
            if args.profile.stat().st_size > 16*1024:
                raise InstallError('프로필 크기는 최대 16 KiB입니다')
            profile_content = args.profile.read_bytes()
            # Reuse the existing validator before making any SSH-side changes.
            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            from setup_robot import read_profile, validate_profile
            validate_profile(read_profile(args.profile))
        print('[사전 검사] SSH 호스트 키는 현장/관리자와 대조하세요. 인증 정보는 저장하지 않습니다.', flush=True)
        check = subprocess.run(ssh_command(args.host, args.port, request), capture_output=True, text=True, timeout=180)
        if check.returncode:
            # Only emit our controlled error prefix, not SSH/credential-helper output.
            detail = next((line for line in check.stderr.splitlines() if line.startswith('LeKiwi: ')), '')
            raise InstallError(detail or 'SSH/사전 검사 실패. 주소·호스트 키·SSH 인증·Pi의 Git 인증·네트워크를 확인하세요')
        preflight = result_from(check.stdout)
        print(json.dumps(preflight, ensure_ascii=False, indent=2))
        if not args.install:
            return 0
        request.update(action='install', profile_base64=base64.b64encode(profile_content).decode('ascii'),
                       serial_port=args.serial_port, confirm_wheel_map=True,
                       camera=args.camera, wrist_camera=args.wrist_camera)
        print('[설치] SSH 터미널의 sudo 요청에 응답하세요. 터미널 출력은 파일로 저장하지 않습니다.', flush=True)
        # Inherit the terminal for SSH/sudo prompts. Result is retrieved separately
        # because capturing a PTY stream would record interactive credentials.
        code = subprocess.call(ssh_command(args.host, args.port, request, interactive=True))
        if code:
            raise InstallError('설치 또는 서비스 검증 실패. Pi의 상태를 확인하고 수동 복구하세요. 자동 덮어쓰기 없음')
        # Retrieve only allowlisted, nonsecret completion fields, not config files.
        result_request = {**request, 'action': 'result'}
        result_request.pop('profile_base64')
        result = subprocess.run(ssh_command(args.host, args.port, result_request), capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise InstallError('설치 후 결과 재검증 실패. 완료로 표시하지 않습니다')
        write_completion(args.output, result_from(result.stdout))
        print('설치 검증 완료. PC 브라우저에서 안내 파일을 여세요: ' + str(args.output.resolve()))
        return 0
    except (InstallError, OSError, ValueError, subprocess.TimeoutExpired, ImportError) as error:
        print('오류: ' + (str(error) if isinstance(error, InstallError) else
                      '파일/의존성/SSH 실행 실패. Python 3.12, PyYAML, 경로와 네트워크를 확인하세요.'), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
