#!/usr/bin/env python3
"""Always-on local controller selector; application login remains independent."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import subprocess
import threading
from urllib.parse import urlsplit

HELPER = '/usr/local/libexec/xlerobot-web-mode'
ROOT = Path(__file__).resolve().parent


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.operation = {'busy': False, 'error': None, 'target': None}
        self.switch_lock = threading.Lock()

    def helper(self, *args):
        result = subprocess.run(['sudo', '-n', HELPER, *args], capture_output=True, text=True, timeout=110)
        try:
            value = json.loads(result.stdout)
        except ValueError:
            raise ValueError('전환 서비스 응답을 확인할 수 없습니다')
        if result.returncode:
            raise ValueError(value.get('error', '전환 실패'))
        return value

    def switch(self, target):
        if target not in ('custom', 'factory'):
            raise ValueError('잘못된 웹앱 선택')
        if not self.switch_lock.acquire(blocking=False):
            raise ValueError('이미 전환 중입니다')
        with self.lock:
            self.operation = {'busy': True, 'error': None, 'target': target}
        def run():
            try:
                self.helper('switch', target)
            except Exception as error:
                with self.lock:
                    self.operation['error'] = str(error)[:500]
            finally:
                with self.lock:
                    self.operation['busy'] = False
                self.switch_lock.release()
        threading.Thread(target=run, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *_):
        pass

    def valid_host(self):
        try:
            host = urlsplit('http://' + self.headers.get('Host', '')).hostname
            if host in ('localhost', 'xlerobot', 'xlerobot.local', 'lekiwi01', 'lekiwi01.local'):
                return True
            address = ipaddress.ip_address(host)
            return address.is_private or address.is_loopback
        except (ValueError, TypeError):
            return False

    def reply(self, code, value):
        data = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self.valid_host():
            return self.reply(403, {'error': 'Invalid host'})
        if self.path == '/':
            body = (ROOT/'web_mode.html').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; frame-ancestors 'none'")
            self.end_headers()
            return self.wfile.write(body)
        if self.path != '/api/status':
            return self.reply(404, {'error': 'Not found'})
        try:
            value = self.server.state.helper('status')
            with self.server.state.lock:
                value['operation'] = dict(self.server.state.operation)
            return self.reply(200, value)
        except Exception as error:
            return self.reply(503, {'error': str(error)[:500]})

    def do_POST(self):
        if not self.valid_host() or self.headers.get('Origin') != 'http://' + self.headers.get('Host', ''):
            return self.reply(403, {'error': '다른 사이트의 요청은 허용하지 않습니다'})
        try:
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                return self.reply(415, {'error': 'JSON required'})
            length = int(self.headers.get('Content-Length', 0))
            if not 0 < length <= 1024:
                return self.reply(413, {'error': 'Request size rejected'})
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('Invalid JSON')
            state = self.server.state
            if self.path != '/api/switch':
                return self.reply(404, {'error': 'Not found'})
            state.switch(data.get('mode'))
            return self.reply(202, {'accepted': True})
        except (ValueError, TypeError) as error:
            return self.reply(409, {'error': str(error)[:500]})


def main():
    server = ThreadingHTTPServer(('0.0.0.0', 8091), Handler)
    server.daemon_threads = True
    server.state = State()
    server.serve_forever()


if __name__ == '__main__':
    main()
