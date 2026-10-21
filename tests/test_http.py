import http.cookiejar
import io
import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'app'))
sys.path.insert(0, str(ROOT/'tools'))
from core import DemoBackend
from server import App, Server
from export_lerobot import uniform_segments, validated_image
from verify_robot import idle_status


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = App(DemoBackend(), '12345678', {'recordings': self.temp.name, 'name': 'Cloud Test'})
        self.server = Server(('127.0.0.1', 0), self.app)
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)
        self.server_thread = threading.Thread(target=lambda:self.server.serve_forever(poll_interval=.02))
        self.worker = threading.Thread(target=self.app.run)
        self.worker.start(); self.server_thread.start()
        self.cookies = http.cookiejar.CookieJar()
        self.client = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(self.cookies))

    def tearDown(self):
        self.server.shutdown(); self.server_thread.join(timeout=2)
        self.app.shutdown.set(); self.worker.join(timeout=2)
        self.app.control.stop(emergency=True); self.app.recorder.close(); self.server.server_close()
        self.temp.cleanup()

    def request(self, path, body=None, origin=None):
        headers = {} if body is None else {'Origin':origin or self.base, 'Content-Type':'application/json'}
        payload = None if body is None else json.dumps(body).encode()
        with self.client.open(urllib.request.Request(self.base+path, data=payload, headers=headers), timeout=15) as result:
            return result.read()

    def data(self, path, body=None): return json.loads(self.request(path, body))
    def pair(self): self.assertTrue(self.data('/api/pair', {'pin':'12345678'})['ok'])

    def test_system_requires_pin_and_expired_session_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as error: self.request('/api/system')
        self.assertEqual(error.exception.code, 401)
        self.pair(); self.assertTrue(self.data('/api/system')['demo'])
        self.app.sessions = {key:time.monotonic()-1 for key in self.app.sessions}
        with self.assertRaises(urllib.error.HTTPError) as error: self.request('/api/system')
        self.assertEqual(error.exception.code, 401)

    def test_wrong_pin_and_foreign_origin(self):
        with self.assertRaises(urllib.error.HTTPError) as error: self.data('/api/pair', {'pin':'0000'})
        self.assertEqual(error.exception.code, 401)
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api/pair', {'pin':'12345678'}, origin='https://example.invalid')
        self.assertEqual(error.exception.code, 403)

    def test_system_read_only_and_no_credentials(self):
        self.pair()
        result = self.data('/api/system')
        self.assertEqual(result['services']['lekiwi-camera.service']['state'], 'not_applicable_demo')
        self.assertIn('tag', result['git'])
        self.assertFalse(result['motor']['physical_stop_verified'])
        self.assertTrue(result['motor']['simulated'])
        self.assertNotIn('12345678', json.dumps(result))
        self.assertEqual(result['storage']['path'], self.temp.name)
        with self.assertRaises(urllib.error.HTTPError) as error: self.request('/api/system', {'command':'touch /tmp/nope'})
        self.assertEqual(error.exception.code, 404)

    def test_demo_jpeg_authentication_and_integrity(self):
        from PIL import Image
        with self.assertRaises(urllib.error.HTTPError) as error: self.request('/api/camera/demo.jpg')
        self.assertEqual(error.exception.code, 401)
        self.pair()
        with Image.open(io.BytesIO(self.request('/api/camera/demo.jpg'))) as frame:
            self.assertEqual(frame.size, (640,480)); frame.verify()

    def test_slam_record_request_rejects_demo_and_invalid_mode(self):
        self.pair();self.data('/api/arm',{})
        self.assertFalse(self.data('/api/status')['recording']['slam']['available'])
        for selected in (True,'yes'):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.data('/api/record/start',{'task':'map','slam':selected})
            self.assertEqual(error.exception.code,409)
        self.assertFalse(self.data('/api/status')['recording']['active'])

    def test_read_only_idle_check_rejects_active_control(self):
        self.assertTrue(idle_status('12345678', self.base)['demo'])
        self.pair(); self.data('/api/arm', {})
        from robot_install import InstallError
        with self.assertRaises(InstallError): idle_status('12345678', self.base)

    def test_single_owner_and_stale_command_rejection(self):
        self.pair(); lease = self.data('/api/arm', {})['lease']
        body = {'lease':lease,'seq':1,'direction':'idle','speed':1/30,'hold':None,'sent_at':time.time()*1000}
        self.assertTrue(self.data('/api/command', body)['ok'])
        with self.assertRaises(urllib.error.HTTPError) as error: self.data('/api/command', body)
        self.assertEqual(error.exception.code, 409)
        self.cookies.clear(); self.pair()
        with self.assertRaises(urllib.error.HTTPError) as error: self.data('/api/command', {**body,'seq':2})
        self.assertEqual(error.exception.code, 409)

    def test_recording_zip_and_export_input_compatibility(self):
        self.pair(); lease = self.data('/api/arm', {})['lease']
        episode_id = self.data('/api/record/start', {'task':'synthetic HTTP compatibility'})['episode_id']
        for seq in range(14):
            self.data('/api/command', {'lease':lease,'seq':seq,'direction':'forward','speed':1/30,
                'hold':'test','sent_at':time.time()*1000})
            time.sleep(.05)
        self.assertGreater(self.data('/api/status')['recording']['elapsed_s'], .5)
        self.data('/api/record/finish', {'outcome':'success'})
        status = self.data('/api/status')
        self.assertFalse(status['armed']); self.assertEqual(status['output_motion'], [0,0,0])
        with zipfile.ZipFile(io.BytesIO(self.request('/api/record/'+episode_id+'/download'))) as archive:
            self.assertIsNone(archive.testzip())
            metadata = json.loads(archive.read(episode_id+'/episode.json'))
            self.assertEqual(metadata['format'], 'lekiwi-episode-v1')
            self.assertTrue(metadata['complete'])
            rows = [json.loads(line) for line in archive.read(episode_id+'/samples.jsonl').splitlines()]
        segments = uniform_segments(rows)
        self.assertTrue(segments)
        image = validated_image(Path(self.temp.name)/episode_id, segments[0][0])
        self.assertTrue(image.is_file())
        self.assertEqual(len(segments[0][0]['state']), 6)
        self.assertEqual(len(segments[0][0]['applied_action']), 3)
        self.assertTrue(any(row['requested_action'] != row['applied_action'] for row in segments[0]))


if __name__ == '__main__':
    unittest.main()
