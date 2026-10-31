"""PIN-protected mobile gateway for the installed native operator.

Only the native operator owns ROS/hardware. This module starts no ROS process.
"""
import argparse
import base64
import hashlib
import http.client
import json
import select
import socket
import struct
import threading
from collections import defaultdict, deque
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit, parse_qs
from map_library import MapLibrary
from server import Handler as AuthHandler
from http.server import ThreadingHTTPServer

ROOT = Path(__file__).parent / 'mobile'
GET_ROUTES = {'/api/info', '/api/status', '/api/maps', '/api/maps/preview', '/api/logs', '/api/network'}
POST_ROUTES = {'/api/control/acquire', '/api/control/release', '/api/motor/power',
 '/api/process/start', '/api/process/stop', '/api/map/save', '/api/explore/start',
 '/api/explore/stop', '/api/nav/initial_pose', '/api/nav/goal', '/api/nav/cancel', '/api/nav/speed'}


def exact(sock, count):
    data = bytearray()
    while len(data) < count:
        part = sock.recv(count-len(data))
        if not part: raise ConnectionError('Upstream disconnected')
        data.extend(part)
    return bytes(data)


def upstream_welcome(sock):
    """Native welcome is one unmasked FIN text frame; reject unexpected framing."""
    head = exact(sock, 2)
    if head[0] != 0x81 or head[1] & 0x80: raise ValueError('Invalid native welcome')
    size = head[1] & 127
    extension = b''
    if size == 126: extension = exact(sock, 2); size = struct.unpack('!H', extension)[0]
    elif size == 127: raise ValueError('Oversized welcome')
    if size > 65535: raise ValueError('Oversized welcome')
    payload = exact(sock, size)
    data = json.loads(payload)
    client_id = data.get('client_id')
    if data.get('type') != 'welcome' or not isinstance(client_id, str) or len(client_id) != 16 or any(c not in '0123456789abcdef' for c in client_id):
        raise ValueError('Invalid native client identity')
    return head+extension+payload, client_id


class MobileHandler(AuthHandler):
    def headers_common(self, type_, length):
        self.send_header('Content-Type', type_)
        self.send_header('Content-Length', str(length))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")

    def device_status(self):
        probe=getattr(self.app,'device_probe',None)
        return probe() if probe else {n:Path('/dev/'+n).exists() for n in ('lekiwi_motor','lekiwi_arm_left','lekiwi_arm_right','ydlidar')}

    def do_GET(self):
        if not self.valid_host(): return self.response(403, {'error':'Invalid host'})
        path = urlsplit(self.path).path
        if path == '/health': return self.response(200, {'ok':True, 'backend':'native', 'hardware_started':False})
        if path == '/ws': return self.websocket()
        if path == '/api/mobile/diagnostics':
            if not self.session():return self.response(401,{'error':'접속 코드를 입력하세요'})
            return self.response(200,{'devices':self.device_status(),'envelope':{'width':0.45,'depth':0.35,'height':0.77,'radius':0.30},'physical_motion_verified':False})
        if path in ('/api/library','/api/maps/export'):
            if not self.session(): return self.response(401, {'error':'접속 코드를 입력하세요'})
            try:
                if path == '/api/library': return self.response(200,self.app.library.read())
                name=parse_qs(urlsplit(self.path).query).get('name',[''])[0]
                body=self.app.library.export(name)
                self.send_response(200);self.headers_common('application/zip',len(body))
                self.send_header('Content-Disposition','attachment; filename=map-export.zip')
                self.end_headers();self.wfile.write(body);return
            except (ValueError,OSError):return self.response(400,{'error':'지도를 내보낼 수 없습니다'})
        if path in GET_ROUTES:
            if not self.session(): return self.response(401, {'error':'접속 코드를 입력하세요'})
            return self.proxy('GET')
        assets = {'/':'index.html','/mobile.js':'mobile.js','/mobile.css':'mobile.css','/icon.svg':'icon.svg','/mission.js':'mission.js','/exploration_mission.js':'exploration_mission.js'}
        name = assets.get(path)
        if path in ('/native/connection.js','/native/format.js','/native/widgets/map_view.js','/native/widgets/canvas.js'): name = path.lstrip('/')
        if name is None: return self.response(404, {'error':'Not found'})
        file = ROOT/name
        if not file.is_file(): return self.response(404, {'error':'Not found'})
        body = file.read_bytes(); self.send_response(200)
        self.headers_common({'html':'text/html','js':'text/javascript','css':'text/css','svg':'image/svg+xml'}[file.suffix[1:]]+'; charset=utf-8',len(body))
        self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        path = urlsplit(self.path).path
        if path == '/api/pair': return super().do_POST()
        if not self.valid_host() or self.headers.get('Origin') != 'http://'+self.headers.get('Host',''):
            return self.response(403, {'error':'다른 사이트의 요청은 허용하지 않습니다'})
        owner = self.session()
        if not owner: return self.response(401, {'error':'접속 코드를 입력하세요'})
        if path not in POST_ROUTES and path != '/api/library/route': return self.response(404, {'error':'Not found'})
        identity = self.headers.get('X-Client-Id','')
        with self.app.auth_lock:
            if self.app.clients.get(identity) != owner: return self.response(403, {'error':'조종 연결을 다시 확인하세요'})
        try:
            length = int(self.headers.get('Content-Length','0'))
            if not 0 < length <= 65536: raise ValueError()
            if self.headers.get('Content-Type','').split(';')[0] != 'application/json': raise ValueError()
            body = self.rfile.read(length)
            if not isinstance(json.loads(body),dict): raise ValueError()
        except (ValueError, OSError): return self.response(400, {'error':'Invalid JSON request'})
        if path == '/api/library/route':
            try:
                data=json.loads(body)
                return self.response(200,{'ok':True,'map':self.app.library.save(data.get('name'),data.get('label',''),data.get('route',[]))})
            except (ValueError,OSError):return self.response(400,{'error':'지도 이름과 경로를 확인하세요'})
        data=json.loads(body)
        starts=(path in ('/api/explore/start','/api/nav/goal') or path=='/api/motor/power' and data.get('enabled') is True or path=='/api/process/start')
        if starts:
            devices=self.device_status()
            missing=[n for n in ('lekiwi_motor','ydlidar') if not devices.get(n)]
            if missing:return self.response(409,{'ok':False,'message':'USB 장치가 인식되지 않아 시작할 수 없습니다: '+', '.join(missing)})
        return self.proxy('POST', body, identity)

    def proxy(self, method, body=None, identity=''):
        conn = http.client.HTTPConnection('127.0.0.1', self.app.native_port, timeout=8)
        try:
            headers={'Origin':f'http://127.0.0.1:{self.app.native_port}', 'Content-Type':'application/json','X-Client-Id':identity}
            conn.request(method,self.path,body=body,headers=headers)
            result=conn.getresponse(); data=result.read(8*1024*1024+1)
            if len(data)>8*1024*1024: raise ValueError('Response too large')
            self.send_response(result.status)
            self.headers_common(result.getheader('Content-Type','application/json'),len(data))
            self.end_headers();self.wfile.write(data)
        except (OSError,ValueError,http.client.HTTPException): self.response(502,{'error':'로보시지 제어 엔진에 연결할 수 없습니다'})
        finally: conn.close()

    def websocket(self):
        owner=self.session()
        if not owner: return self.response(401,{'error':'접속 코드를 입력하세요'})
        if self.headers.get('Origin') != 'http://'+self.headers.get('Host',''): return self.response(403,{'error':'Origin rejected'})
        key=self.headers.get('Sec-WebSocket-Key','')
        try:
            if len(base64.b64decode(key,validate=True))!=16 or self.headers.get('Sec-WebSocket-Version')!='13' or self.headers.get('Upgrade','').lower()!='websocket': raise ValueError()
        except ValueError: return self.response(400,{'error':'Invalid WebSocket handshake'})
        upstream=None; identity=None
        try:
            upstream=socket.create_connection(('127.0.0.1',self.app.native_port),timeout=5)
            host=f'127.0.0.1:{self.app.native_port}'
            upstream.sendall((f'GET /ws HTTP/1.1\r\nHost: {host}\r\nOrigin: http://{host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
            header=bytearray()
            while not header.endswith(b'\r\n\r\n'):
                header.extend(exact(upstream,1))
                if len(header)>16384: raise ValueError('Invalid upgrade')
            accept=base64.b64encode(hashlib.sha1((key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
            if not header.startswith(b'HTTP/1.1 101 ') and not header.startswith(b'HTTP/1.0 101 '): raise ValueError('Native upgrade refused')
            fields={line.split(':',1)[0].lower():line.split(':',1)[1].strip() for line in header.decode().split('\r\n')[1:] if ':' in line}
            if fields.get('sec-websocket-accept')!=accept: raise ValueError('Invalid accept')
            welcome,identity=upstream_welcome(upstream)
            with self.app.auth_lock: self.app.clients[identity]=owner
            self.send_response(101);self.send_header('Upgrade','websocket');self.send_header('Connection','Upgrade');self.send_header('Sec-WebSocket-Accept',accept);self.end_headers()
            self.wfile.flush(); self.connection.sendall(welcome)
            self.connection.settimeout(5);upstream.settimeout(5)
            while self.session()==owner:
                ready,_,_=select.select([self.connection,upstream],[],[],1)
                for source in ready:
                    data=source.recv(65536)
                    if not data: return
                    (upstream if source is self.connection else self.connection).sendall(data)
        except (OSError,ValueError):
            # Close both ends: native hub releases the corresponding lease on disconnect.
            pass
        finally:
            self.close_connection=True
            if upstream: upstream.close()
            if identity:
                with self.app.auth_lock: self.app.clients.pop(identity,None)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);parser.add_argument('--port',type=int,default=8090);parser.add_argument('--host',default='0.0.0.0');parser.add_argument('--native-port',type=int,default=8080)
    parser.add_argument('--map-dir',default=str(Path.home()/'maps/lekiwi'));parser.add_argument('--library',default=str(Path.home()/'.local/share/xlerobot-mobile/library.json'))
    args=parser.parse_args();config=json.loads(Path(args.config).read_text())
    server=ThreadingHTTPServer((args.host,args.port),MobileHandler)
    server.app=SimpleNamespace(pin=str(config['pin']),auth_lock=threading.RLock(),sessions={},attempts=defaultdict(deque),clients={},native_port=args.native_port,library=MapLibrary(args.map_dir,args.library))
    try:server.serve_forever()
    finally:server.server_close()

if __name__=='__main__':main()
