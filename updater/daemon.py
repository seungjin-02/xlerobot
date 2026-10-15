#!/usr/bin/env python3
"""Root-owned local admin service; fixed protocol, no command/path/URL API."""
import argparse
from collections import deque
import hashlib
import hmac
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import secrets
import socket
import threading
import time

from common import UpdateError
from engine import Engine, Runtime
from releases import Releases

class Admin:
    def __init__(self, engine, password_hash, salt):
        self.engine, self.password_hash, self.salt = engine, password_hash, salt
        self.sessions, self.attempts = {}, deque()
        self.lock, self.job_lock = threading.Lock(), threading.Lock()
        self.job_error = None

    def login(self, password):
        if not isinstance(password, str) or not 16 <= len(password) <= 256: raise UpdateError('administrator_login_failed')
        with self.lock:
            now = time.monotonic()
            while self.attempts and now-self.attempts[0]>60: self.attempts.popleft()
            if len(self.attempts)>=5: raise UpdateError('administrator_rate_limited')
            self.attempts.append(now)
            actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(self.salt), n=16384, r=8, p=1).hex()
            if not hmac.compare_digest(actual, self.password_hash): raise UpdateError('administrator_login_failed')
            self.sessions = {k:v for k,v in self.sessions.items() if v>now}
            if len(self.sessions)>=10: raise UpdateError('administrator_session_limit')
            token=secrets.token_urlsafe(32)
            self.sessions[token]=now+900
            return token

    def authenticated(self, cookie):
        try: token=SimpleCookie(cookie)['lekiwi_admin'].value
        except (KeyError, TypeError, ValueError): return None
        with self.lock:
            return token if self.sessions.get(token, 0)>time.monotonic() else None

    def launch(self, method, *args):
        if not self.job_lock.acquire(blocking=False): raise UpdateError('update_busy')
        self.job_error=None
        def work():
            try: method(*args)
            except UpdateError as error: self.job_error=str(error)
            except Exception: self.job_error='administrator_operation_failed'
            finally: self.job_lock.release()
        threading.Thread(target=work, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *args): pass  # Never log credentials, cookies, requests or Git stderr.

    def valid_host(self):
        return self.headers.get('Host') in ('127.0.0.1:8093', 'localhost:8093')

    def reply(self, status, value, cookie=None):
        body=json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json')
        self.headers_safe(len(body))
        if cookie: self.send_header('Set-Cookie',cookie)
        self.end_headers();self.wfile.write(body)

    def headers_safe(self, size):
        self.send_header('Content-Length', str(size))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")

    def do_GET(self):
        if not self.valid_host(): return self.reply(403,{'error':'invalid_host'})
        files={'/':('admin.html','text/html; charset=utf-8'),'/admin.js':('admin.js','text/javascript'),'/admin.css':('admin.css','text/css')}
        if self.path in files:
            name,mime=files[self.path];body=Path(__file__).with_name(name).read_bytes()
            self.send_response(200);self.send_header('Content-Type',mime);self.headers_safe(len(body));self.end_headers();self.wfile.write(body);return
        if not self.server.admin.authenticated(self.headers.get('Cookie','')): return self.reply(401,{'error':'administrator_login_required'})
        if self.path=='/api/status':
            engine=self.server.admin.engine
            public={k:engine.state.get(k) for k in ('phase','tag','commit','error','updated_at')}
            return self.reply(200,{**public,'busy':self.server.admin.job_lock.locked(),'job_error':self.server.admin.job_error})
        return self.reply(404,{'error':'not_found'})

    def do_POST(self):
        try:
            if not self.valid_host() or self.headers.get('Origin')!='http://'+self.headers.get('Host',''):
                return self.reply(403,{'error':'invalid_origin'})
            if self.headers.get('Content-Type','').split(';')[0]!='application/json': return self.reply(415,{'error':'json_required'})
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=2048: return self.reply(413,{'error':'request_too_large'})
            self.connection.settimeout(5)
            data=json.loads(self.rfile.read(length))
            if not isinstance(data,dict): raise UpdateError('invalid_request')
            admin=self.server.admin
            if self.path=='/api/login':
                if set(data)!={'password'}: raise UpdateError('invalid_request')
                token=admin.login(data['password'])
                return self.reply(200,{'ok':True},f'lekiwi_admin={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=900')
            token=admin.authenticated(self.headers.get('Cookie',''))
            if not token: return self.reply(401,{'error':'administrator_login_required'})
            if self.path=='/api/logout':
                with admin.lock: admin.sessions.pop(token,None)
                return self.reply(200,{'ok':True},'lekiwi_admin=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
            if self.path=='/api/releases' and not data:
                if not admin.engine.mutex.acquire(blocking=False): raise UpdateError('update_busy')
                try: result=admin.engine.sources.list(admin.engine.baseline())
                finally: admin.engine.mutex.release()
                return self.reply(200,{'releases':result})
            if self.path=='/api/apply' and set(data)=={'tag','commit','motor_power_isolated'}:
                admin.launch(admin.engine.update,data['tag'],data['commit'],data['motor_power_isolated'])
                return self.reply(202,{'accepted':True})
            if self.path=='/api/confirm-recovery' and set(data)=={'motor_power_isolated'}:
                admin.launch(admin.engine.confirm_recovery,data['motor_power_isolated'])
                return self.reply(202,{'accepted':True})
            return self.reply(404,{'error':'not_found'})
        except (ValueError,TypeError,UpdateError) as error:
            return self.reply(409,{'error':str(error) if isinstance(error,UpdateError) else 'invalid_request'})
        except Exception:
            return self.reply(503,{'error':'administrator_operation_failed'})


class AdminServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16
    def __init__(self, address):
        super().__init__(address, Handler)
        self.slots = threading.BoundedSemaphore(16)
    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try: super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise
    def process_request_thread(self, request, address):
        try: super().process_request_thread(request, address)
        finally: self.slots.release()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy',default='/etc/lekiwi-updater/policy.json')
    args=parser.parse_args()
    if os.geteuid()!=0: raise SystemExit('Run only the root-installed system service.')
    path=Path(args.policy)
    if path.is_symlink() or path.stat().st_uid!=0 or path.stat().st_mode & 0o022:
        raise SystemExit('Policy must be root-owned and not writable by other users.')
    policy=json.loads(path.read_text())
    sources=Releases(policy['cache'],policy['keyring'],policy['trusted_fingerprints'],policy['worker_uid'],policy['worker_gid'])
    engine=Engine(policy['root'],sources,Runtime(policy['config_file']),policy['snapshot_paths'])
    engine.recover()
    credential_path=Path('/etc/lekiwi-updater/admin.json')
    if credential_path.is_symlink() or credential_path.stat().st_uid!=0 or credential_path.stat().st_mode & 0o077:
        raise SystemExit('Administrator credentials must be root-owned 0600.')
    credentials=json.loads(credential_path.read_text())
    server=AdminServer(('127.0.0.1',8093))
    server.daemon_threads=True
    server.admin=Admin(engine,credentials['hash'],credentials['salt'])
    notify=os.environ.get('NOTIFY_SOCKET')
    if notify:
        with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as ready:
            ready.connect('\0'+notify[1:] if notify.startswith('@') else notify)
            ready.sendall(b'READY=1')
    server.serve_forever()

if __name__=='__main__': main()
