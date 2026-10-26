#!/usr/bin/env python3
import urllib.request
import argparse
import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import signal
import re
import tempfile
import zipfile
import shutil
import threading
import time
from collections import defaultdict, deque
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from core import Controller, ControlError, DemoBackend
from system_info import SystemInfo, storage_info
from maintenance import Maintenance

ROOT = Path(__file__).resolve().parent

class App:
    def __init__(self, backend, pin, config=None):
        self.control = Controller(backend)
        self.maintenance = Maintenance()
        self.pin = str(pin)
        self.sessions = {}
        self.attempts = defaultdict(deque)
        self.auth_lock = threading.Lock()
        self.shutdown = threading.Event()
        self.fault = None
        from recorder import EpisodeRecorder, DemoCameraFeed
        config = config or {}
        profile={**getattr(backend,'output_parameters',{'demo':True}), 'robot_name':config.get('name','LeKiwi'), 'camera_source':config.get('camera','0'), 'camera_rotation':config.get('camera_rotation',0)}
        self.device_name=config.get('name','LeKiwi')
        self.has_arm=bool(config.get('has_arm',False))
        self.cameras=config.get('cameras') or [{'role':'front','source':config.get('camera','0'),'rotation':config.get('camera_rotation',0)}]
        profile.update(has_arm=self.has_arm,cameras=self.cameras)
        self.ending_owner=None; self.ending_until_ns=0
        from slam import configuration, available
        slam_config = configuration(config.get('slam'),getattr(backend,'output_parameters',{}))
        self.recorder = EpisodeRecorder(config.get('recordings', str(Path.home()/'lekiwi-recordings')),
                                        profile,
                                        feed=DemoCameraFeed() if isinstance(backend,DemoBackend) else None,
                                        slam_config=slam_config,slam_supported=available(isinstance(backend,DemoBackend)))
        self.system_info = SystemInfo(ROOT.parent, self.recorder.root, isinstance(backend, DemoBackend))
        from autonomy import Autonomy
        self.autonomy = Autonomy(self, config)

    def record_sample(self):
        if not self.recorder.active: return
        with self.control.lock:
            automatic = self.autonomy
            if automatic.busy and automatic.guard and self.recorder.owner == automatic.owner:
                guard=automatic.guard
                age=(time.monotonic()-guard.received)*1000 if guard.received is not None else None
                observation=self.control.backend.observation() if hasattr(self.control.backend,'observation') else None
                self.recorder.sample(guard.command,guard.output,observation,self.control.backend.status().get('motor_ready'),
                    age,not automatic.stop_event.is_set() and age is not None and age <= 300)
                return
            age = (time.monotonic()-self.control.last_packet)*1000 if self.control.owner else None
            observation = self.control.backend.observation() if hasattr(self.control.backend,'observation') else None
            self.recorder.sample(self.control.desired_motion,self.control.output_motion,observation,
                                 self.control.backend.status().get('motor_ready'),age,
                                 (self.control.owner==self.recorder.owner and age is not None and age <= 600) or (self.control.owner is None and self.ending_owner==self.recorder.owner and time.monotonic_ns()<self.ending_until_ns))

    def episodes(self):
        result=[]
        if not self.recorder.root.exists(): return result
        for path in sorted(self.recorder.root.glob('*'),reverse=True)[:20]:
            if not re.fullmatch(r'\d{8}T\d{6}Z-[a-f0-9]{8}',path.name): continue
            try:
                info=json.loads((path/'episode.json').read_text())
                result.append({key:info.get(key) for key in ['episode_id','task','outcome','complete','samples','valid_samples']})
                result[-1]['slam'] = info.get('slam')
                result[-1]['control_mode'] = info.get('device_profile',{}).get('control_mode','manual')
            except (OSError,ValueError): continue
        return result

    def run(self):
        while not self.shutdown.wait(.02):
            try:
                with self.control.lock:
                    if self.autonomy.busy:self.autonomy.tick()
                    else:self.control.tick()
                self.record_sample()
                self.fault = None
            except Exception:
                logging.exception('Control loop failed')
                with self.control.lock:
                    if self.control.owner:
                        self.control._stop('제어 오류로 정지했습니다')
                self.fault = '제어 연결 오류: 상태를 확인하세요'
                if self.autonomy.busy:self.autonomy.request_stop(emergency=True)
                time.sleep(.1)

class Handler(BaseHTTPRequestHandler):
    server_version = 'LeKiwiPhone/2'
    protocol_version = 'HTTP/1.1'
    def log_message(self, fmt, *args):
        # Do not log URLs, cookies, PINs or bodies.
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    @property
    def app(self): return self.server.app

    def response(self, code, data, cookie=None):
        body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(code)
        if code >= 400:
            self.close_connection = True
            self.send_header('Connection', 'close')
        self.headers_common('application/json; charset=utf-8', len(body))
        if cookie: self.send_header('Set-Cookie', cookie)
        self.end_headers(); self.wfile.write(body)

    def headers_common(self, type_, length):
        self.send_header('Content-Type', type_)
        self.send_header('Content-Length', str(length))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' http:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")

    def session(self):
        try:
            cookie = SimpleCookie(self.headers.get('Cookie', ''))
            value = cookie['lekiwi_session'].value
        except (KeyError, ValueError): return None
        with self.app.auth_lock:
            if self.app.sessions.get(value, 0) > time.monotonic(): return value
        return None

    def valid_host(self):
        try:
            host = urlsplit('http://' + self.headers.get('Host', '')).hostname
            if host in ('localhost', 'lekiwi01', 'lekiwi01.local'): return True
            address = ipaddress.ip_address(host)
            return address.is_private or address.is_loopback
        except ValueError: return False

    def do_GET(self):
        if not self.valid_host(): return self.response(403, {'error': 'Invalid host'})
        path = urlsplit(self.path).path
        if path == '/health':
            return self.response(200, {'ok': True, 'demo': isinstance(self.app.control.backend, DemoBackend)})
        if path == '/api/system':
            owner = self.session()
            if not owner: return self.response(401, {'error': '접속 코드를 입력하세요'})
            info = self.app.system_info.snapshot(self.app.control.status(owner), self.app.device_name, self.app.fault)
            info['updates'] = self.app.maintenance.status()
            return self.response(200, info)
        if path == '/api/camera/demo.jpg':
            if not self.session(): return self.response(401, {'error': '접속 코드를 입력하세요'})
            if not isinstance(self.app.control.backend, DemoBackend):
                return self.response(404, {'error': '데모 전용 영상입니다'})
            body = self.app.recorder.feed.frame['jpeg']
            self.send_response(200); self.headers_common('image/jpeg', len(body))
            self.end_headers(); self.wfile.write(body)
            return
        if path == '/api/status':
            owner = self.session()
            if not owner: return self.response(401, {'error': '접속 코드를 입력하세요'})
            data = self.app.control.status(owner)
            data['fault'] = self.app.fault
            data['device_name'] = self.app.device_name
            data['has_arm'] = self.app.has_arm
            try:
                with urllib.request.urlopen('http://127.0.0.1:8080/api/cameras',timeout=.3) as response:
                    camera_health={c['role']:c['connected'] for c in json.load(response)}
            except (OSError,ValueError): camera_health={}
            demo = isinstance(self.app.control.backend, DemoBackend)
            data['cameras'] = [{'role':c['role'],'index':i,'connected':demo or camera_health.get(c['role'],False), 'simulated':demo} for i,c in enumerate(self.app.cameras)]
            data['recording'] = self.app.recorder.status(owner)
            data['storage'] = storage_info(self.app.recorder.root)
            data['episodes'] = self.app.episodes()
            data['updates'] = self.app.maintenance.status()
            data['autonomy'] = self.app.autonomy.status(owner)
            return self.response(200, data)
        if path == '/api/autonomy/map':
            if not self.session():return self.response(401,{'error':'접속 코드를 입력하세요'})
            return self.response(200,self.app.autonomy.map_view())
        match = re.fullmatch(r'/api/record/([0-9]{8}T[0-9]{6}Z-[a-f0-9]{8})/download',path)
        if match:
            if not self.session(): return self.response(401,{'error':'접속 코드를 입력하세요'})
            episode = self.app.recorder.root / match.group(1)
            if not (episode/'episode.json').is_file(): return self.response(404,{'error':'기록이 없습니다'})
            if self.app.recorder.episode_id==match.group(1) and (self.app.recorder.active or self.app.recorder.finishing):
                return self.response(409,{'error':'기록을 먼저 종료하세요'})
            try:
                total=sum(p.stat().st_size for p in episode.rglob('*') if p.is_file())
                if shutil.disk_usage(episode).free < total + 128*1024**2: return self.response(409,{'error':'압축 파일 생성 공간이 부족합니다. PC에서 원본을 복사하세요'})
                with tempfile.TemporaryDirectory(dir=self.app.recorder.root) as temp:
                    archive=Path(temp)/'episode.zip'
                    with zipfile.ZipFile(archive,'w',zipfile.ZIP_STORED) as zipped:
                        for p in episode.rglob('*'):
                            if p.is_file(): zipped.write(p,match.group(1)+'/'+str(p.relative_to(episode)))
                    self.send_response(200);self.headers_common('application/zip',archive.stat().st_size)
                    self.send_header('Content-Disposition',f'attachment; filename="{match.group(1)}.zip"');self.end_headers()
                    with archive.open('rb') as source: shutil.copyfileobj(source,self.wfile,64*1024)
            except (BrokenPipeError,ConnectionResetError): pass
            except OSError: return self.response(503,{'error':'기록 파일을 읽지 못했습니다'})
            return
        files = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8'), '/icon.svg': ('icon.svg', 'image/svg+xml')}
        if path not in files: return self.response(404, {'error': 'Not found'})
        name, mime = files[path]; body = (ROOT / name).read_bytes()
        self.send_response(200); self.headers_common(mime, len(body)); self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        gate = None
        try:
            if not self.valid_host(): return self.response(403, {'error': 'Invalid host'})
            origin = self.headers.get('Origin')
            if origin != 'http://' + self.headers.get('Host', ''):
                return self.response(403, {'error': '다른 사이트의 요청은 허용하지 않습니다'})
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                return self.response(415, {'error': 'JSON required'})
            length = int(self.headers.get('Content-Length', 0))
            if not 0 < length <= 2048: return self.response(413, {'error': 'Request size rejected'})
            self.connection.settimeout(1)
            data = json.loads(self.rfile.read(length))
            self.connection.settimeout(15)
            if not isinstance(data, dict): raise ValueError('Invalid JSON')
            path = urlsplit(self.path).path
            if path == '/api/pair':
                now = time.monotonic(); ip = self.client_address[0]
                with self.app.auth_lock:
                    attempts = self.app.attempts[ip]
                    while attempts and now - attempts[0] > 60: attempts.popleft()
                    if len(attempts) >= 10: return self.response(429, {'error': '1분 뒤 다시 시도하세요'})
                    attempts.append(now)
                    if not hmac.compare_digest(str(data.get('pin', '')), self.app.pin):
                        return self.response(401, {'error': '접속 코드가 맞지 않습니다'})
                    self.app.sessions = {k: v for k, v in self.app.sessions.items() if v > now}
                    if len(self.app.sessions) > 100: return self.response(429, {'error': '접속 수 제한'})
                    token = secrets.token_urlsafe(32); self.app.sessions[token] = now + 43200
                return self.response(200, {'ok': True}, f'lekiwi_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200')
            owner = self.session()
            if not owner: return self.response(401, {'error': '접속 코드를 입력하세요'})
            if path in ('/api/arm', '/api/prepare', '/api/record/start', '/api/command','/api/autonomy/start'):
                gate = self.app.maintenance.allow()
                gate.__enter__()
            if path in ('/api/arm','/api/prepare','/api/command','/api/record/start') and self.app.autonomy.busy:
                raise ControlError('자율주행 중에는 수동 조종·별도 기록을 시작할 수 없습니다')
            if path == '/api/autonomy/start':
                self.app.autonomy.start(owner,data)
                return self.response(202,{'ok':True,'state':'starting'})
            if path == '/api/autonomy/pause':
                self.app.autonomy.pause(owner);return self.response(200,{'ok':True})
            if path == '/api/autonomy/resume':
                self.app.autonomy.resume(owner);return self.response(200,{'ok':True})
            if path == '/api/autonomy/stop':
                self.app.autonomy.request_stop(owner,emergency=True)
                return self.response(200,{'ok':True})
            if path == '/api/record/start':
                with self.app.control.lock:
                    if self.app.control.owner != owner:
                        raise ControlError('조종 시작을 먼저 누른 뒤 기록하세요')
                self.app.recorder.profile={**self.app.recorder.profile, **getattr(self.app.control.backend,'output_parameters',{'demo':True}), 'robot_name':self.app.device_name, 'camera_source':self.app.recorder.profile.get('camera_source','0'), 'camera_rotation':self.app.recorder.profile.get('camera_rotation',0)}
                self.app.recorder.profile['control_mode']='manual'
                episode=self.app.recorder.start(owner,data.get('task',''),slam=data.get('slam',False))
                return self.response(200,{'episode_id':episode})
            if path == '/api/record/finish':
                if self.app.recorder.owner not in (None,owner): raise ControlError('기록을 시작한 폰에서 종료하세요')
                outcome=data.get('outcome','unfinished')
                if outcome not in ('success','failure','unfinished'): raise ControlError('잘못된 결과 표시')
                if self.app.autonomy.busy:
                    self.app.autonomy.request_stop(owner,outcome=outcome)
                    return self.response(202,{'episode':None,'finishing':True})
                self.app.ending_owner=owner;self.app.ending_until_ns=time.monotonic_ns()+350000000
                self.app.control.stop(owner)
                try:
                    time.sleep(.3)
                    result=self.app.recorder.finish(owner,outcome)
                finally:
                    self.app.ending_owner=None
                return self.response(200,{'episode':result})
            if path == '/api/prepare':
                with self.app.control.lock:
                    if self.app.control.owner: raise ControlError('조종을 먼저 종료하세요')
                    if isinstance(self.app.control.backend, DemoBackend):
                        return self.response(200, {'ok': True})
                    self.app.control.backend.prepare_fast()
                return self.response(200, {'ok': True})
            if path == '/api/arm':
                if self.app.fault: return self.response(409, {'error': self.app.fault})
                return self.response(200, {'lease': self.app.control.arm(owner)})
            if path == '/api/command':
                sent = data.get('sent_at')
                if not isinstance(sent, (int, float)) or isinstance(sent, bool) or not -100 <= time.time() * 1000 - sent <= 1000:
                    raise ControlError('지연된 명령을 거부했습니다')
                self.app.control.command(owner, data.get('lease'), data.get('seq'), data.get('direction'), data.get('speed'), data.get('hold'))
                self.app.recorder.event({'type':'command','direction':data.get('direction'),'speed':data.get('speed'),'phone_sent_wall_ms':data.get('sent_at')})
                return self.response(200, {'ok': True})
            if path == '/api/stop':
                # Any paired phone can stop this app's session, never arm someone else's.
                self.app.control.stop(owner, emergency=True)
                self.app.autonomy.request_stop(owner,emergency=True)
                return self.response(200, {'ok': True})
            return self.response(404, {'error': 'Not found'})
        except (ControlError, ValueError, TypeError) as e:
            return self.response(409, {'error': str(e)})
        except Exception:
            logging.exception('Request failed')
            return self.response(503, {'error': '로봇 제어 실패: 상태와 연결을 확인하세요'})
        finally:
            if gate is not None:
                gate.__exit__(None, None, None)

class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16
    def __init__(self, address, app):
        super().__init__(address, Handler)
        self.app = app
        self.slots = threading.BoundedSemaphore(24)
    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            request.close(); return
        try: super().process_request(request, address)
        except Exception: self.slots.release(); raise
    def process_request_thread(self, request, address):
        try: super().process_request_thread(request, address)
        finally: self.slots.release()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8090)
    parser.add_argument('--recordings',type=Path)
    parser.add_argument('--config', default=str(Path.home() / '.config/lekiwi-phone/config.json'))
    args = parser.parse_args()
    if args.demo:
        config = {'pin': '12345678'}; backend = DemoBackend()
    else:
        config = json.loads(Path(args.config).read_text())
        from ros_backend import RosBackend
        backend = RosBackend(config['profile'], config.get('workspace'))
    if args.recordings: config['recordings']=str(args.recordings)
    app = App(backend, config['pin'], config); server = Server((args.host, args.port), app)
    worker = threading.Thread(target=app.run, daemon=True); worker.start()
    def shutdown(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGINT, shutdown); signal.signal(signal.SIGTERM, shutdown)
    print(f'LeKiwi phone controller: http://{args.host}:{args.port} (motors disabled on startup)', flush=True)
    try: server.serve_forever(poll_interval=.1)
    finally:
        app.autonomy.request_stop(emergency=True)
        if app.autonomy.thread:app.autonomy.thread.join(timeout=20)
        app.shutdown.set(); worker.join(timeout=1)
        app.control.stop(emergency=True)
        try: app.recorder.close()
        finally: backend.close(); server.server_close()

if __name__ == '__main__': main()
