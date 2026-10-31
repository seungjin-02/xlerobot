import base64
import http.client
import json
import socket
import struct
import sys
import threading
import unittest
from collections import defaultdict,deque
from pathlib import Path
from types import SimpleNamespace
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from mobile_gateway import MobileHandler,upstream_welcome

class GatewayTests(unittest.TestCase):
 def setUp(self):
  self.server=ThreadingHTTPServer(('127.0.0.1',0),MobileHandler)
  self.server.app=SimpleNamespace(pin='test-only',auth_lock=threading.RLock(),sessions={},attempts=defaultdict(deque),clients={},native_port=1,device_probe=lambda:{'lekiwi_motor':True,'ydlidar':True})
  self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
  self.port=self.server.server_port
 def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join()
 def request(self,path,body=None,cookie=None,identity=''):
  c=http.client.HTTPConnection('127.0.0.1',self.port,timeout=3)
  headers={'Origin':f'http://127.0.0.1:{self.port}','Content-Type':'application/json','X-Client-Id':identity}
  if cookie:headers['Cookie']=cookie
  c.request('POST' if body is not None else 'GET',path,json.dumps(body) if body is not None else None,headers)
  r=c.getresponse();out=(r.status,dict(r.getheaders()),r.read());c.close();return out
 def pair(self):
  status,headers,_=self.request('/api/pair',{'pin':'test-only'});self.assertEqual(status,200)
  return headers['Set-Cookie'].split(';')[0]
 def test_pin_required_for_native_read_and_ws(self):
  self.assertEqual(self.request('/api/status')[0],401)
  self.assertEqual(self.request('/ws')[0],401)
 def test_pair_and_protected_assets(self):
  cookie=self.pair();self.assertEqual(self.request('/api/status',cookie=cookie)[0],502)
  self.assertEqual(self.request('/')[0],200)
  self.assertEqual(self.request('/native/widgets/map_view.js')[0],200)
  self.assertEqual(self.request('/native/../../server.py')[0],404)
 def test_native_identity_cannot_be_borrowed(self):
  first=self.pair();second=self.pair()
  owner=first.split('=',1)[1];self.server.app.clients['0123456789abcdef']=owner
  self.assertEqual(self.request('/api/nav/goal',{'x':0},second,'0123456789abcdef')[0],403)
  self.assertEqual(self.request('/api/nav/goal',{'x':0},first,'0123456789abcdef')[0],502)
 def test_unexposed_arms_and_network_mutations_rejected(self):
  cookie=self.pair()
  for path in ('/api/arm/start','/api/network/ap_off','/api/prepare'):
   self.assertEqual(self.request(path,{},cookie)[0],404)
 def test_missing_devices_block_start_but_not_status_diagnostics(self):
  cookie=self.pair();self.server.app.clients['0123456789abcdef']=cookie.split('=',1)[1]
  self.server.app.device_probe=lambda:{'lekiwi_motor':False,'ydlidar':False}
  self.assertEqual(self.request('/api/process/start',{'name':'bringup'},cookie,'0123456789abcdef')[0],409)
  self.assertEqual(self.request('/api/mobile/diagnostics',cookie=cookie)[0],200)
 def test_authenticated_api_forwarding_preserves_body_and_origin(self):
  calls=[]
  class Native(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_POST(self):
    data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
    calls.append((self.path,data,self.headers['Origin'],self.headers['X-Client-Id']))
    body=b'{"ok":true,"message":"mock-only"}'
    self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
  native=ThreadingHTTPServer(('127.0.0.1',0),Native)
  worker=threading.Thread(target=native.serve_forever,daemon=True);worker.start()
  try:
   self.server.app.native_port=native.server_port;cookie=self.pair();identity='0123456789abcdef';self.server.app.clients[identity]=cookie.split('=',1)[1]
   commands=[('/api/nav/goal',{'x':1,'y':2,'yaw':0}),('/api/explore/start',{}),('/api/process/start',{'name':'mapping','options':{}}),('/api/nav/speed',{'percent':50})]
   for path,body in commands:self.assertEqual(self.request(path,body,cookie,identity)[0],200)
   self.assertEqual([(c[0],c[1]) for c in calls],commands)
   self.assertTrue(all(c[2]==f'http://127.0.0.1:{native.server_port}' and c[3]==identity for c in calls))
  finally:native.shutdown();native.server_close();worker.join()
 def test_welcome_identity_validated(self):
  a,b=socket.socketpair()
  try:
   payload=json.dumps({'type':'welcome','client_id':'0123456789abcdef'}).encode();wire=bytes([0x81,len(payload)])+payload;b.sendall(wire)
   self.assertEqual(upstream_welcome(a),(wire,'0123456789abcdef'))
  finally:a.close();b.close()
 def test_unexpected_native_frame_rejected(self):
  a,b=socket.socketpair()
  try:
   b.sendall(b'\x82\x00')
   with self.assertRaises(ValueError):upstream_welcome(a)
  finally:a.close();b.close()
if __name__=='__main__':unittest.main()
