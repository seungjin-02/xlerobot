import copy
import io
import http.cookiejar
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools/web_modes'))
from web_mode_policy import require_idle
import web_mode_root as root
import web_mode_server as web


CUSTOM = {'armed': False, 'motor_ready': False, 'autonomy': {'busy': False},
          'recording': {'active': False}, 'output_motion': [0, 0, 0]}
FACTORY = {'processes': {k: {'state': 'stopped'} for k in ('bringup', 'mapping', 'navigation')},
           'motor': {'ready': None, 'is_powered_by_us': False}, 'teleop_arm': {},
           'control': {'holder': None}, 'exploration': {'state': 'idle'}}


class ModePolicyTests(unittest.TestCase):
    def test_idle_both(self):
        require_idle('custom', CUSTOM)
        require_idle('factory', FACTORY)

    def test_custom_busy_reasons(self):
        for key in ('armed', 'autonomy', 'recording', 'output_motion'):
            value = copy.deepcopy(CUSTOM)
            value[key] = {'armed': True, 'autonomy': {'busy': True},
                          'recording': {'active': True}, 'output_motion': [.01, 0, 0]}[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                require_idle('custom', value)

    def test_completed_map_save_is_idle_for_switching(self):
        value=copy.deepcopy(FACTORY);value['processes']['save_map']={'state':'succeeded'}
        require_idle('factory',value)

    def test_factory_activities(self):
        for key in ('processes', 'motor', 'teleop_arm', 'control', 'calibration', 'zmq_host'):
            value = copy.deepcopy(FACTORY)
            value[key] = {'processes': {'bringup': {'state': 'external'}, 'mapping': {'state': 'stopped'}, 'navigation': {'state': 'stopped'}},
                          'motor': {'ready': True}, 'teleop_arm': {'is_torque_maybe_on': True},
                          'control': {'holder': {'client_id': None}}, 'calibration': {'follower': {'state': 'recording'}},
                          'zmq_host': {'session': 'active'}}[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                require_idle('factory', value)

    def test_unknown_status_rejected(self):
        for mode in ('custom', 'factory', 'shell command'):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                require_idle(mode, {})


class SwitchTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        (self.directory/'state.json').write_text('{"mode":"custom"}')
        self.mode = 'custom'
        self.calls = []
        def stop():
            self.calls.append('stop')
            self.mode = 'off'
        def start(mode):
            self.calls.append('start '+mode)
            self.mode = mode
        self.start = start
        self.patches = [patch.object(root, 'STATE', self.directory),
            patch.object(root, 'require_target_devices', lambda _: None),
            patch.object(root, 'status', lambda: {'mode': self.mode}),
            patch.object(root, 'api_status', lambda _: copy.deepcopy(CUSTOM)),
            patch.object(root, 'serial_holders', lambda **_: []),
            patch.object(root, 'stop_all', stop), patch.object(root, 'start_mode', start)]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_stop_precedes_start_and_persists(self):
        root.switch('factory')
        self.assertEqual(self.calls, ['stop', 'start factory'])
        self.assertEqual(json.loads((self.directory/'state.json').read_text())['mode'], 'factory')

    def test_busy_never_stops_source(self):
        with patch.object(root, 'api_status', return_value={**CUSTOM, 'armed': True}):
            with self.assertRaises(ValueError):
                root.switch('factory')
        self.assertEqual(self.calls, [])

    def test_unknown_serial_holder_blocks(self):
        with patch.object(root, 'serial_holders', return_value=[321]):
            with self.assertRaises(ValueError):
                root.switch('factory')
        self.assertEqual(self.calls, [])

    def test_missing_target_devices_never_stops_or_starts_services(self):
        with patch.object(root, 'require_target_devices', side_effect=ValueError('USB disconnected')):
            with self.assertRaisesRegex(ValueError, 'USB disconnected'):
                root.switch('custom')
        self.assertEqual(self.calls, [])

    def test_failed_target_rolls_back_without_persisting(self):
        def fail_factory(mode):
            self.start(mode)
            if mode == 'factory':
                raise RuntimeError('Target not healthy')
        with patch.object(root, 'start_mode', fail_factory):
            with self.assertRaisesRegex(RuntimeError, 'Target not healthy'):
                root.switch('factory')
        self.assertEqual(self.calls, ['stop', 'start factory', 'stop', 'start custom'])
        self.assertEqual(self.mode, 'custom')
        self.assertEqual(json.loads((self.directory/'state.json').read_text())['mode'], 'custom')


class TargetDeviceTests(unittest.TestCase):
    def test_disconnected_devices_block_custom_but_allow_factory_diagnosis(self):
        with patch.object(root.Path, 'exists', return_value=False):
            with self.assertRaisesRegex(ValueError, '/dev/lekiwi_motor'):
                root.require_target_devices('custom')
            root.require_target_devices('factory')


class ModeHttpTests(unittest.TestCase):
    def setUp(self):
        self.server = web.ThreadingHTTPServer(('127.0.0.1', 0), web.Handler)
        self.server.daemon_threads = True
        self.server.state = web.State()
        self.calls = []
        def helper(*args):
            self.calls.append(args)
            return {'mode': 'custom'}
        self.server.state.helper = helper
        self.worker = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=.01))
        self.worker.start()
        self.base = 'http://127.0.0.1:'+str(self.server.server_port)
        self.client = urllib.request.build_opener(urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def tearDown(self):
        self.server.shutdown()
        self.worker.join(timeout=2)
        self.server.server_close()

    def request(self, path, data=None, origin=None):
        headers = {'Content-Type': 'application/json', 'Origin': origin or self.base}
        req = urllib.request.Request(self.base+path, headers=headers,
            data=json.dumps(data).encode() if data is not None else None)
        try:
            with self.client.open(req) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as response:
            return response.code, json.load(response)

    def test_status_without_login(self):
        self.assertEqual(self.request('/api/status')[0], 200)
        self.assertEqual(self.calls, [('status',)])

    def test_cross_origin_switch_rejected(self):
        self.assertEqual(self.request('/api/switch', {'mode': 'factory'}, 'http://evil.invalid')[0], 403)
        self.assertEqual(self.calls, [])

    def test_login_endpoint_removed(self):
        self.assertEqual(self.request('/api/login', {'pin': 'irrelevant'})[0], 404)
        self.assertEqual(self.calls, [])

    def test_invalid_mode_cannot_invoke_helper(self):
        self.assertEqual(self.request('/api/switch', {'mode': 'custom; command'})[0], 409)
        self.assertEqual(self.calls, [])

    def test_switch_without_login_and_status(self):
        self.assertEqual(self.request('/api/switch', {'mode': 'factory'})[0], 202)
        deadline = time.monotonic()+2
        while self.server.state.operation['busy'] and time.monotonic()<deadline:
            time.sleep(.01)
        self.assertIn(('switch', 'factory'), self.calls)
        self.assertEqual(self.request('/api/status')[1]['mode'], 'custom')

    def test_concurrent_switch_rejected(self):
        self.server.state.switch_lock.acquire()
        try:
            self.assertEqual(self.request('/api/switch', {'mode': 'factory'})[0], 409)
            self.assertEqual(self.calls, [])
        finally:
            self.server.state.switch_lock.release()


class SharedNativeModeTests(unittest.TestCase):
    def test_shared_backend_plus_mobile_is_one_controller(self):
        with patch.object(root, 'shared_engine', return_value=True), patch.object(root, 'active', side_effect=lambda unit,user=False: unit in (root.FACTORY,'lekiwi-phone.service')):
            self.assertEqual(root.status()['mode'],'custom')

    def test_legacy_sensor_service_still_counts_as_conflict(self):
        with patch.object(root, 'shared_engine', return_value=True), patch.object(root, 'active', return_value=True):
            self.assertEqual(root.status()['mode'],'conflict')

    def test_mobile_without_engine_is_not_reported_healthy(self):
        with patch.object(root, 'shared_engine', return_value=True), patch.object(root, 'active', side_effect=lambda unit,user=False: unit=='lekiwi-phone.service'):
            self.assertEqual(root.status()['mode'],'conflict')

    def test_shared_mobile_uses_native_idle_checks(self):
        with patch.object(root, 'shared_engine', return_value=True):
            root.idle('custom',FACTORY)
            busy=copy.deepcopy(FACTORY);busy['motor']['ready']=True
            with self.assertRaises(ValueError):root.idle('custom',busy)

    def test_shared_start_never_starts_legacy_drivers(self):
        state={'mode':'custom','custom_units':{'lekiwi-phone.service':True}}
        with patch.object(root,'shared_engine',return_value=True), patch.object(root,'command') as command, patch.object(root,'api_status',return_value=FACTORY),patch.object(root,'status',return_value=state), patch.object(root.urllib.request,'build_opener') as opener:
            opener.return_value.open.side_effect=lambda *a,**k:io.BytesIO(b'{"backend":"native"}')
            root.start_mode('custom')
            self.assertEqual(command.call_count,2)
            flattened=str(command.call_args_list)
            self.assertNotIn('lekiwi-camera.service',flattened)
            self.assertNotIn('lekiwi-lidar.service',flattened)


if __name__ == '__main__':
    unittest.main()
