import contextlib
import fcntl
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'updater'))
sys.path.insert(0,str(ROOT/'app'))
from common import UpdateError, atomic_json, manifest, snapshot, switch_link
from engine import Engine, Runtime
from releases import Releases
from daemon import Admin, Handler
from maintenance import Maintenance
from core import ControlError
from http.server import ThreadingHTTPServer

OLD='a'*40
NEW='b'*40

class Source:
    def __init__(self): self.refreshed=0
    def refresh(self): self.refreshed+=1
    def describe(self,tag,old): return {'tag':tag,'commit':NEW,'notes':'Fixture','changes':['app/server.py']}
    def extract(self,sha,target):
        target.mkdir();(target/'app.py').write_text('new source')
    def list(self,old): return [self.describe('v2.0.0',old)]

class Robot:
    def __init__(self): self.calls=[];self.fail_new=False;self.fail_old=False;self.armed=False;self.on_health=None
    def idle(self):
        if self.armed: raise UpdateError('robot_not_idle')
        return {'armed':False}
    def application_idle(self): return self.idle()
    def service(self,verb): self.calls.append(verb)
    def health(self,sha):
        self.calls.append('health:'+sha)
        if self.on_health:self.on_health(sha)
        if (sha==NEW and self.fail_new) or (sha==OLD and self.fail_old): raise UpdateError('unhealthy')

class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name);self.root=self.home/'managed';(self.root/'releases'/OLD).mkdir(parents=True)
        switch_link(self.root/'current',self.root/'releases'/OLD)
        self.paths={}
        for name in ('config','recordings','workspace'):
            p=self.home/name;p.mkdir();(p/'keep').write_text(name+' fixture');self.paths[name]=p
        self.source=Source();self.robot=Robot();self.engine=Engine(self.root,self.source,self.robot,self.paths)
        self.before={k:manifest(p) for k,p in self.paths.items()}

    def apply(self): self.engine.update('v2.0.0',NEW,True)

    def test_app_disabled_update_without_physical_isolation(self):
        self.engine.update('v2.0.0',NEW,False,True)
        self.assertEqual(self.engine.state['phase'],'succeeded')
        self.assertFalse((self.root/'maintenance.json').exists())

    def test_app_disabled_state_rechecked_after_network_preparation(self):
        original=self.source.refresh
        def refresh():
            original()
            self.robot.armed=True
        self.source.refresh=refresh
        with self.assertRaises(UpdateError):
            self.engine.update('v2.0.0',NEW,False,True)
        self.assertEqual(self.robot.calls,[])
        self.assertEqual(self.engine.baseline(),OLD)

    def test_success_snapshot_preservation_atomic_switch_and_unlock(self):
        self.apply()
        self.assertEqual(self.engine.baseline(),NEW);self.assertEqual(self.engine.state['phase'],'succeeded')
        self.assertFalse((self.root/'maintenance.json').exists())
        self.assertEqual(self.before,{k:manifest(p) for k,p in self.paths.items()})
        backup=Path(self.engine.state['backup'])
        for name,path in self.paths.items():self.assertEqual(manifest(backup/name),manifest(path))
        self.assertEqual((backup/'config-manifest.json').stat().st_mode & 0o777,0o600)
        self.assertEqual(self.robot.calls,['stop','start','health:'+NEW])

    def test_active_robot_refused_before_network_or_service_stop(self):
        self.robot.armed=True
        with self.assertRaises(UpdateError):self.apply()
        self.assertEqual(self.source.refreshed,0);self.assertEqual(self.robot.calls,[])
        self.assertEqual(self.engine.baseline(),OLD);self.assertFalse((self.root/'maintenance.json').exists())

    def test_physical_confirmation_and_exact_commit_required(self):
        for sha,ack in ((NEW,False),('main',True),('c'*40,True)):
            with self.assertRaises(UpdateError):self.engine.update('v2.0.0',sha,ack)
        self.assertEqual(self.engine.baseline(),OLD);self.assertEqual(self.robot.calls,[])

    def test_new_service_failure_rolls_back_without_data_loss(self):
        self.robot.fail_new=True
        with self.assertRaises(UpdateError):self.apply()
        self.assertEqual(self.engine.baseline(),OLD);self.assertEqual(self.engine.state['phase'],'rolled_back')
        self.assertEqual(self.before,{k:manifest(p) for k,p in self.paths.items()})
        self.assertFalse((self.root/'maintenance.json').exists())

    def test_changed_data_saved_before_backup_restore(self):
        def change(sha):
            if sha==NEW:(self.paths['recordings']/'unexpected').write_text('preserve new data')
        self.robot.on_health=change
        with self.assertRaises(UpdateError):self.apply()
        self.assertEqual(self.engine.state['phase'],'rolled_back')
        backup=Path(self.engine.state['backup'])
        rescued=list((backup/'post-failure').glob('recordings-*/unexpected'))
        self.assertEqual(rescued[0].read_text(),'preserve new data')
        self.assertEqual(self.before,{k:manifest(p) for k,p in self.paths.items()})

    def test_failed_rollback_keeps_durable_motor_gate(self):
        self.robot.fail_new=self.robot.fail_old=True
        with self.assertRaises(UpdateError):self.apply()
        self.assertEqual(self.engine.state['phase'],'manual_recovery_required')
        with self.assertRaises(ControlError):
            with Maintenance(self.root,required=True).allow():pass
        again=Engine(self.root,self.source,self.robot,self.paths);again.recover()
        self.assertEqual(again.state['phase'],'manual_recovery_required')

    def test_interruption_after_switch_restores_previous_but_stays_locked(self):
        def crash(sha):
            if sha==NEW:raise SystemExit('simulated power loss')
        self.robot.on_health=crash
        with self.assertRaises(SystemExit):self.apply()
        self.assertEqual(self.engine.baseline(),NEW)
        self.robot.on_health=None
        reboot=Engine(self.root,self.source,self.robot,self.paths);calls=list(self.robot.calls);reboot.recover()
        self.assertEqual(reboot.baseline(),OLD);self.assertEqual(reboot.state['phase'],'recovered_unverified')
        self.assertEqual(self.robot.calls,calls) # boot recovery does not start services or motors
        self.assertTrue((self.root/'maintenance.json').exists())
        reboot.confirm_recovery(True)
        self.assertFalse((self.root/'maintenance.json').exists());self.assertEqual(reboot.state['phase'],'recovered')

    def test_backup_io_failure_never_switches_and_restarts_old(self):
        with patch('engine.snapshot',side_effect=OSError('fixture disk failure')):
            with self.assertRaises(UpdateError):self.apply()
        self.assertEqual(self.engine.baseline(),OLD);self.assertEqual(self.engine.state['phase'],'rolled_back')

    def test_process_lock_blocks_duplicate_update_and_app_mutations(self):
        with self.engine.exclusive():
            with self.assertRaises(UpdateError):self.apply()
            with self.assertRaises(ControlError):
                with Maintenance(self.root,required=True).allow():pass
        with Maintenance(self.root,required=True).allow():pass

    def test_network_preparation_keeps_motor_gate_closed(self):
        def refresh():
            with self.assertRaises(ControlError):
                with Maintenance(self.root,required=True).allow():pass
        self.source.refresh=refresh;self.apply()

    def test_external_symlink_backup_refused_and_absent_dataset_stays_absent(self):
        absent=self.home/'absent';target=self.home/'absent-copy'
        self.assertFalse(snapshot(absent,target)['exists']);self.assertFalse(target.exists())
        (self.paths['recordings']/'escape').symlink_to('/etc/hosts')
        with self.assertRaises(UpdateError):self.apply()
        self.assertEqual(self.engine.baseline(),OLD)

    def test_relative_workspace_symlink_snapshot_and_restore(self):
        workspace=self.paths['workspace']
        nested=workspace/'install';nested.mkdir()
        (nested/'relative').symlink_to('../keep')
        self.engine.update('v2.0.0',NEW,False,True)
        backup=Path(self.engine.state['backup'])
        self.assertEqual((backup/'workspace/install/relative').read_text(),'workspace fixture')
        self.assertEqual(manifest(workspace),manifest(backup/'workspace',links_root=workspace))
        (workspace/'keep').write_text('changed')
        self.engine.restore_files(backup)
        self.assertEqual((workspace/'install/relative').read_text(),'workspace fixture')

    def test_internal_workspace_symlink_backup_is_verified(self):
        w=self.paths['workspace'];(w/'linked').symlink_to(w/'keep')
        target=self.home/'copy';before=snapshot(w,target)
        self.assertEqual(before,manifest(target,links_root=w))

class ManagedGateTests(unittest.TestCase):
    def test_legacy_unchanged_but_managed_missing_state_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            with Maintenance(tmp,required=False).allow():pass
            with self.assertRaises(ControlError):
                with Maintenance(tmp,required=True).allow():pass

    def test_incomplete_idle_response_is_never_accepted(self):
        robot=Runtime('/not/read')
        for value in ({},{'armed':False,'motor_ready':0,'other_publishers':0,'available':True,'recording':{'active':False,'finishing':False}}):
            with patch.object(robot,'get',return_value=value),self.assertRaises(UpdateError):robot.idle()

class ApplicationMaintenanceTests(unittest.TestCase):
    def test_app_motor_idle_requires_explicit_no_base_process(self):
        runtime=Runtime('/unused')
        value={'armed':False,'available':False,'motor_ready':None,'other_publishers':0,
            'recording':{'active':False,'finishing':False},'base_running':False}
        with patch.object(runtime,'get',return_value=value):
            self.assertEqual(runtime.application_idle(),value)
        for field,invalid in [('base_running',True),('base_running',None),('armed',True),
                ('motor_ready',True),('other_publishers',1)]:
            with self.subTest(field=field,invalid=invalid),patch.object(runtime,'get',return_value={**value,field:invalid}):
                with self.assertRaises(UpdateError):runtime.application_idle()

class AdminTests(unittest.TestCase):
    def setUp(self):
        self.salt='12'*16;self.password='separate-admin-fixture'
        self.hash=hashlib.scrypt(self.password.encode(),salt=bytes.fromhex(self.salt),n=16384,r=8,p=1).hex()
        class FakeEngine:
            state={'phase':'idle'}
        self.admin=Admin(FakeEngine(),self.hash,self.salt)

    def test_pin_does_not_authenticate_admin_and_rate_limit_is_global(self):
        for _ in range(5):
            with self.assertRaises(UpdateError):self.admin.login('wrong-password-fixture')
        with self.assertRaisesRegex(UpdateError,'rate_limited'):self.admin.login(self.password)

    def test_session_expires_and_authentication_uses_separate_cookie(self):
        token=self.admin.login(self.password)
        self.assertIsNone(self.admin.authenticated('lekiwi_session='+token))
        self.assertEqual(self.admin.authenticated('lekiwi_admin='+token),token)
        self.admin.sessions[token]=0
        self.assertIsNone(self.admin.authenticated('lekiwi_admin='+token))

    def test_admin_http_origin_unknown_operation_and_credentials_not_echoed(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.admin=self.admin
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        client=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        base='http://127.0.0.1:'+str(server.server_port)
        def post(path,body,origin='http://127.0.0.1:8093'):
            request=urllib.request.Request(base+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Host':'127.0.0.1:8093','Origin':origin})
            return client.open(request,timeout=5)
        with self.assertRaises(urllib.error.HTTPError) as result:post('/api/login',{'password':self.password},'http://attacker.invalid')
        self.assertEqual(result.exception.code,403)
        with post('/api/login',{'password':self.password}) as response:
            self.assertIn('HttpOnly',response.headers['Set-Cookie']);self.assertNotIn(self.password,response.read().decode())
        with self.assertRaises(urllib.error.HTTPError) as result:post('/api/shell',{'command':'touch /tmp/not-run'})
        self.assertEqual(result.exception.code,404)
        with post('/api/logout',{}) as response:self.assertEqual(response.status,200)
        with self.assertRaises(urllib.error.HTTPError) as result:post('/api/apply',{'tag':'v2.0.0','commit':NEW,'motor_power_isolated':True})
        self.assertEqual(result.exception.code,401)

class SignatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.keytemp=tempfile.TemporaryDirectory();cls.keys=Path(cls.keytemp.name)
        cls.sign=cls.keys/'sign';cls.sign.mkdir(mode=0o700)
        cls.verify=cls.keys/'verify';cls.verify.mkdir(mode=0o700)
        def gpg(home,*args,input=None):
            return subprocess.check_output(['gpg','--homedir',str(home),'--batch',*args],input=input,stderr=subprocess.DEVNULL)
        gpg(cls.sign,'--passphrase','','--quick-generate-key','Phase2 Fixture <fixture@example.invalid>','ed25519','sign','0')
        listing=gpg(cls.sign,'--with-colons','--list-keys').decode()
        cls.fingerprint=next(l.split(':')[9] for l in listing.splitlines() if l.startswith('fpr:'))
        public=gpg(cls.sign,'--export',cls.fingerprint);gpg(cls.verify,'--import',input=public)

    @classmethod
    def tearDownClass(cls):
        for home in (cls.sign,cls.verify):subprocess.run(['gpgconf','--homedir',str(home),'--kill','gpg-agent'],capture_output=True)
        cls.keytemp.cleanup()

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.repo=Path(self.tmp.name)/'repo';self.repo.mkdir()
        self.env={**os.environ,'GNUPGHOME':str(self.sign),'GIT_CONFIG_GLOBAL':'/dev/null'}
        self.git('init','-q','-b','main');self.git('config','user.name','Fixture');self.git('config','user.email','fixture@example.invalid')
        (self.repo/'app').mkdir();(self.repo/'app/server.py').write_text('old fixture')
        self.commit('baseline');self.old=self.git('rev-parse','HEAD')
        meta={'schema':1,'kind':'application','qualified':True,'config_schema':1,
              'recording_schema':'lekiwi-episode-v1','platform':'ubuntu-24.04-aarch64','updater_protocol':1,'notes':'Fixture release'}
        (self.repo/'update-release.json').write_text(json.dumps(meta));(self.repo/'app/server.py').write_text('new fixture')
        self.commit('application release');self.new=self.git('rev-parse','HEAD');self.tag('v2.0.0')
        self.source=Releases(self.repo,self.verify,[self.fingerprint],os.getuid(),os.getgid())

    def git(self,*args,input=None):
        return subprocess.check_output(['git','-C',str(self.repo),*args],env=self.env,input=input,stderr=subprocess.DEVNULL).decode().strip()
    def commit(self,message):self.git('add','.');self.git('commit','-qm',message)
    def tag(self,name):self.git('-c','user.signingkey='+self.fingerprint,'tag','-s','-m','Fixture qualification',name)

    def test_real_signed_tag_verification_and_safe_archive_extract(self):
        release=self.source.describe('v2.0.0',self.old)
        self.assertEqual(release['commit'],self.new);self.assertTrue(release['qualified_by_trusted_signer'])
        target=Path(self.tmp.name)/'staged';self.source.extract(self.new,target)
        self.assertEqual((target/'app/server.py').read_text(),'new fixture')
        self.assertEqual(target.stat().st_mode & 0o777,0o755)
        self.assertEqual(json.loads((target/'.lekiwi-release.json').read_text())['commit'],self.new)

    def test_unsigned_and_untrusted_tags_are_rejected(self):
        self.git('tag','v2.0.1')
        with self.assertRaises(UpdateError):self.source.describe('v2.0.1',self.old)
        untrusted=Releases(self.repo,self.verify,['0'*40],os.getuid(),os.getgid())
        with self.assertRaisesRegex(UpdateError,'untrusted'):untrusted.describe('v2.0.0',self.old)

    def test_altered_tag_payload_fails_cryptographic_verification(self):
        tag=self.git('cat-file','tag','refs/tags/v2.0.0').replace('Fixture qualification','Changed qualification')+'\n'
        changed=self.git('hash-object','-t','tag','-w','--stdin',input=tag.encode())
        self.git('update-ref','refs/tags/v2.0.0',changed)
        with self.assertRaises(UpdateError):self.source.describe('v2.0.0',self.old)

    def test_dependency_change_requires_manual_upgrade(self):
        (self.repo/'install.sh').write_text('# changed dependency installer')
        self.commit('installer changed');self.tag('v2.1.0')
        with self.assertRaisesRegex(UpdateError,'manual_update'):self.source.describe('v2.1.0',self.old)

    def test_unqualified_release_and_data_migration_are_rejected(self):
        p=self.repo/'update-release.json';meta=json.loads(p.read_text());meta['qualified']=False;p.write_text(json.dumps(meta))
        self.commit('not qualified');self.tag('v2.2.0')
        with self.assertRaisesRegex(UpdateError,'manual_migration'):self.source.describe('v2.2.0',self.old)

    def test_archive_symlink_and_traversal_are_rejected(self):
        import io,tarfile
        for name,kind in (('../escape',tarfile.REGTYPE),('app/escape',tarfile.SYMTYPE)):
            blob=io.BytesIO()
            with tarfile.open(fileobj=blob,mode='w') as archive:
                member=tarfile.TarInfo(name);member.type=kind;member.linkname='/etc/passwd';archive.addfile(member)
            with patch.object(self.source,'git',return_value=blob.getvalue()):
                with self.assertRaises(UpdateError):self.source.extract(self.new,Path(self.tmp.name)/('bad-'+str(kind)))

class AppHTTPGateTests(unittest.TestCase):
    def test_authenticated_drive_requests_blocked_while_stop_and_status_stay_available(self):
        import server
        from core import DemoBackend
        with tempfile.TemporaryDirectory() as tmp:
            app=server.App(DemoBackend(),'12345678',{'recordings':str(Path(tmp)/'records')})
            app.maintenance=Maintenance(Path(tmp)/'managed',required=True)
            web_server=server.Server(('127.0.0.1',0),app)
            t=threading.Thread(target=web_server.serve_forever,daemon=True);t.start()
            client=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            base='http://127.0.0.1:'+str(web_server.server_port)
            def post(path,data):
                return client.open(urllib.request.Request(base+path,data=json.dumps(data).encode(),headers={'Content-Type':'application/json','Origin':base}),timeout=5)
            try:
                post('/api/pair',{'pin':'12345678'}).close()
                for path in ('/api/arm','/api/prepare','/api/record/start','/api/command'):
                    with self.assertRaises(urllib.error.HTTPError) as error:post(path,{})
                    self.assertEqual(error.exception.code,409)
                with post('/api/stop',{}) as response:self.assertEqual(response.status,200)
                with client.open(base+'/api/status') as response:self.assertFalse(json.load(response)['armed'])
                with client.open(base+'/api/system') as response:self.assertTrue(json.load(response)['updates']['blocked'])
            finally:
                web_server.shutdown();web_server.server_close();app.recorder.close()

    def test_managed_version_comes_from_root_staged_metadata(self):
        import system_info
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'LEKIWI_MANAGED_UPDATES':'1'}):
            p=Path(tmp)/'.lekiwi-release.json';p.write_text(json.dumps({'commit':NEW,'tag':'v2.0.0'}))
            version=system_info.git_version(tmp)
            self.assertEqual(version['commit'],NEW);self.assertEqual(version['tag'],'v2.0.0');self.assertTrue(version['managed'])

class AdditionalRecoveryTests(unittest.TestCase):
    setUp = TransactionTests.setUp
    apply = TransactionTests.apply
    def test_partial_service_stop_failure_attempts_previous_start(self):
        calls=[]
        def service(verb):
            calls.append(verb)
            if len(calls)==1:raise UpdateError('partial_service_stop')
        self.robot.service=service
        with self.assertRaises(UpdateError):self.apply()
        self.assertIn('start',calls);self.assertEqual(self.engine.state['phase'],'rolled_back')

    def test_stale_marker_after_success_requires_explicit_verification(self):
        self.engine.reserve();self.engine.recover()
        self.assertEqual(self.engine.state['phase'],'recovered_unverified')
        with self.assertRaises(UpdateError):self.engine.confirm_recovery(False)
        self.assertTrue((self.root/'maintenance.json').exists())
        self.engine.confirm_recovery(True);self.assertFalse((self.root/'maintenance.json').exists())

    def test_interrupted_incomplete_backup_is_never_restored(self):
        with patch('engine.snapshot',side_effect=SystemExit('power loss while copying')):
            with self.assertRaises(SystemExit):self.apply()
        reboot=Engine(self.root,self.source,self.robot,self.paths)
        with patch.object(reboot,'restore_files') as restore:
            reboot.recover();restore.assert_not_called()
        self.assertEqual(self.before,{k:manifest(p) for k,p in self.paths.items()})
        self.assertEqual(reboot.state['phase'],'recovered_unverified')

class ProvisionPlanTests(unittest.TestCase):
    def test_plan_has_no_privileged_side_effects_and_never_echoes_robot_secrets(self):
        import pwd
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);config=home/'config';config.mkdir()
            p=config/'config.json';p.write_text(json.dumps({'recordings':str(home/'records'),'workspace':str(home/'workspace'),
                'camera':'/dev/null','pin':'PRIVATE_ROBOT_PIN','wifi_password':'PRIVATE_AP_PASSWORD'}))
            args=[sys.executable,str(ROOT/'tools/provision_updater.py'),'--robot-user',pwd.getpwuid(os.getuid()).pw_name,
                '--config',str(p),'--baseline-commit',OLD,'--signer','A'*40,'--public-key',str(home/'unread-key')]
            output=subprocess.check_output(args,text=True)
            self.assertNotIn('PRIVATE_ROBOT_PIN',output);self.assertNotIn('PRIVATE_AP_PASSWORD',output)
            self.assertEqual(list(home.iterdir()),[config])
