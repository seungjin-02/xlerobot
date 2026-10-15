#!/usr/bin/env python3
"""Read-only on-robot release checks; never arms, stops, updates or writes config."""
import argparse
import getpass
import http.cookiejar
import json
import sys
import urllib.request

from robot_install import InstallError, verify_services


def idle_status(pin, base='http://127.0.0.1:8090'):
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}),
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    request = urllib.request.Request(base+'/api/pair', data=json.dumps({'pin': pin}).encode(),
        headers={'Content-Type': 'application/json', 'Origin': base})
    with client.open(request, timeout=5) as response:
        if not json.load(response).get('ok'):
            raise InstallError('PIN 인증 실패')
    with client.open(base+'/api/status', timeout=5) as response:
        status = json.load(response)
    validate_idle_status(status)
    return status


def validate_idle_status(status):
    if not isinstance(status, dict):
        raise InstallError('상태 응답을 확인할 수 없습니다')
    recording = status.get('recording')
    if (type(status.get('armed')) is not bool or
            'motor_ready' not in status or
            (status['motor_ready'] is not None and type(status['motor_ready']) is not bool) or
            type(status.get('available')) is not bool or
            type(status.get('other_publishers')) is not int or status['other_publishers'] < 0 or
            not isinstance(recording, dict) or
            any(type(recording.get(key)) is not bool for key in ('active', 'finishing'))):
        raise InstallError('조종/기록 상태 필드가 누락됐거나 유효하지 않습니다. 대기로 간주하지 않습니다')
    if status['armed'] or status['motor_ready'] or status['other_publishers']:
        raise InstallError('조종/모터 준비/다른 제어 프로그램이 활성 상태입니다. 먼저 종료하세요')
    if recording['active'] or recording['finishing']:
        raise InstallError('기록/저장이 진행 중입니다. 먼저 종료하세요')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--idle', action='store_true', help='PIN을 표시하지 않고 조종·기록 대기 확인')
    args = parser.parse_args(argv)
    try:
        verify_services()
        if args.idle:
            status = idle_status(getpass.getpass('웹앱 PIN: '))
            print('PASS: 소프트웨어 조종/기록 대기. 모터 통신 확인 가능: ' + str(bool(status.get('available'))))
        print('PASS: 웹·카메라 서비스 및 HTTP/JPEG 응답. 물리적 정지는 별도 확인하세요.')
        return 0
    except (InstallError, OSError, ValueError):
        print('FAIL: 서비스·카메라·인증·조종/기록 상태를 확인하세요. 업데이트를 진행하지 마세요.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
