"""Synthetic admin UI fixture. No root/systemd/Git network/motor operations."""
import argparse
import hashlib
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'updater'))
from common import switch_link
from engine import Engine
from daemon import Admin, Handler

class Source:
    def refresh(self): pass
    def describe(self,tag,old):return {'tag':tag,'commit':'b'*40,'notes':'합성 검증 릴리스 <script>window.pwned=true</script>','changes':['app/server.py']}
    def list(self,old):return [] if old=='b'*40 else [self.describe('v2.0.0',old)]
    def extract(self,sha,path):path.mkdir();(path/'fixture').write_text('synthetic release')
class Robot:
    def idle(self):return {'armed':False}
    def application_idle(self):return self.idle()
    def service(self,verb):pass
    def health(self,sha):time.sleep(.3)
class LocalFixture(Handler):
    def valid_host(self):return self.headers.get('Host')=='127.0.0.1:'+str(self.server.server_port)

def main():
    p=argparse.ArgumentParser();p.add_argument('--port',required=True,type=int);a=p.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        home=Path(tmp);root=home/'managed';(root/'releases'/('a'*40)).mkdir(parents=True)
        switch_link(root/'current',root/'releases'/('a'*40))
        data=home/'records';data.mkdir();(data/'keep').write_text('fixture records')
        engine=Engine(root,Source(),Robot(),{'recordings':data})
        salt='12'*16
        hashed=hashlib.scrypt(b'separate-admin-fixture',salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
        server=ThreadingHTTPServer(('127.0.0.1',a.port),LocalFixture);server.daemon_threads=True
        server.admin=Admin(engine,hashed,salt);server.serve_forever()
if __name__=='__main__':main()
