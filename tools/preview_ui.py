#!/usr/bin/env python3
"""Local, read-only UI preview. No ROS, robot sockets, credentials or data writes."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]/'app/mobile'
ASSETS={'/mobile.css','/mobile.js','/mission.js','/exploration_mission.js','/icon.svg','/native/format.js','/native/widgets/map_view.js','/native/widgets/canvas.js'}
STATUS={'type':'status','pose':{'map':None},'motor':{'ready':None,'is_powered_by_us':False},'control':{'holder':None},'processes':{k:{'state':'stopped'} for k in ('bringup','mapping','navigation')},'warnings':['UI 미리보기입니다. 실제 로봇 상태를 수신하지 않습니다.'],'teleop':{'is_allowed':False,'blocked_reason':'UI 미리보기 · 실제 로봇에 연결하지 않습니다.','limits':{'source':'preview'},'pads':{'drive':{'levels':[],'max_level':0},'mapping':{'levels':[],'max_level':0}}}}
CONNECTION='''export class Connection {
 constructor(toast){this.toast=toast;this.listeners=new Map();this.isOpen=false;this.clientId='local-preview';}
 on(type,callback){if(!this.listeners.has(type))this.listeners.set(type,new Set());this.listeners.get(type).add(callback);return()=>this.listeners.get(type).delete(callback);}
 emit(type,data){for(const f of this.listeners.get(type)??[])f(data);}
 connect(){queueMicrotask(async()=>{this.isOpen=true;this.emit('welcome',{type:'welcome',client_id:this.clientId});this.emit('link','open');const s=await this.get('/api/status');this.emit('status',s);});}
 subscribe(){}
 send(){return false;}
 async get(path){const r=await fetch(path,{cache:'no-store'});return r.ok?r.json():null;}
 async post(){const result={ok:false,message:'UI 미리보기에서는 로봇 조작과 저장을 실행하지 않습니다.'};this.toast(result.message);return result;}
}
'''

class Preview(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def reply(self,code,body,mime='application/json; charset=utf-8'):
  if isinstance(body,dict):body=json.dumps(body,ensure_ascii=False).encode()
  if isinstance(body,str):body=body.encode()
  self.send_response(code);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'");self.end_headers();self.wfile.write(body)
 def do_GET(self):
  path=urlsplit(self.path).path
  if path=='/':
   html=(ROOT/'index.html').read_text(encoding='utf-8')
   banner='<aside class="preview-banner" role="status"><strong>UI 미리보기 · 로봇 미연결</strong><span>실제 조작·저장 없이 화면만 확인합니다.</span><a href="/">제어 화면 보기</a> · <a href="/?login=1">로그인 화면 보기</a></aside>'
   return self.reply(200,html.replace('<body>','<body>'+banner),'text/html; charset=utf-8')
  if path=='/native/connection.js':return self.reply(200,CONNECTION,'text/javascript; charset=utf-8')
  if path=='/api/status':return self.reply(200,STATUS)
  if path=='/api/maps':return self.reply(200,{'maps':[],'map_dir':'로봇 미연결'})
  if path=='/api/library':return self.reply(200,{'version':1,'maps':{}})
  if path=='/api/mobile/diagnostics':return self.reply(200,{'devices':{'lekiwi_motor':False,'ydlidar':False},'physical_motion_verified':False})
  if path=='/api/logs':return self.reply(200,{'message':'로봇 미연결 · 실제 로그 없음'})
  if path not in ASSETS:return self.reply(404,{'error':'Local preview resource not found'})
  p=ROOT/path.lstrip('/');mime={'.css':'text/css','.js':'text/javascript','.svg':'image/svg+xml'}[p.suffix]+'; charset=utf-8'
  data=p.read_text(encoding='utf-8')
  if path=='/mobile.css':data+='\n.preview-banner{max-width:1000px;margin:16px auto 0;padding:14px 18px;border:1px dashed var(--accent);border-radius:12px;color:var(--accent);font-size:13px;line-height:1.7}.preview-banner span{display:block;color:var(--muted)}.preview-banner a{color:var(--accent)}\n'
  if path=='/mobile.js':
   data=data.replace("fetch('/api/status').then(r=>{if(r.ok)open();}).catch(()=>{});", "if(!new URLSearchParams(location.search).has('login'))open();")
   data=data.replace("?'연결됨':'연결 끊김'","?'미리보기':'미연결'").replace("?'로봇 연결됨':'연결 확인 필요'","?'UI 미리보기':'미연결'")
   data=data.replace('USB 장치 미인식 · 전원을 끄고 허브·전원·케이블 점검이 필요합니다.','UI 미리보기 · 로봇 미연결 · 실제 조작은 실행되지 않습니다.').replace("'미인식'","'미연결'").replace("'정상':'끊김'","'미리보기':'미연결'")
  return self.reply(200,data,mime)
 def do_POST(self):return self.reply(401,{'error':'미리보기에는 접속 코드가 필요 없습니다. 위의 ‘제어 화면 보기’를 눌러 주세요.'})

def main():
 p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=18090);args=p.parse_args()
 server=ThreadingHTTPServer(('127.0.0.1',args.port),Preview)
 print(f'UI preview: http://127.0.0.1:{args.port}/',flush=True)
 try:server.serve_forever()
 except KeyboardInterrupt:pass
 finally:server.server_close()
if __name__=='__main__':main()
