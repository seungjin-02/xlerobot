import base64
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'tools'))
import setup_robot
import robot_install
import install_assistant


class ReinstallPreservationTests(unittest.TestCase):
    def test_reinstall_keeps_robot_settings_credentials_and_recordings(self):
        import yaml
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp); config_dir = home/'.config/lekiwi-phone'; config_dir.mkdir(parents=True)
            workspace = home/'ros_ws'; (workspace/'install').mkdir(parents=True)
            (workspace/'install/setup.bash').write_text('# fixture')
            profile = yaml.safe_load((ROOT/'profiles/standard-sts3215.yaml').read_text())
            profile['lekiwi_node']['ros__parameters']['serial_port'] = '/dev/null'
            profile['lekiwi_node']['ros__parameters']['speed_tick_limit'] = 1234
            profile_path = config_dir/'robot-profile.yaml'; profile_path.write_text(yaml.safe_dump(profile))
            recordings = home/'custom-recordings'; recordings.mkdir(); (recordings/'untouched').write_text('keep data')
            old = {'profile':str(profile_path),'workspace':str(workspace),'camera':'/dev/v4l/by-path/front',
                   'camera_rotation':180,'cameras':[{'role':'front','source':'/dev/v4l/by-path/front','rotation':180},
                        {'role':'wrist','source':'/dev/v4l/by-path/wrist','rotation':90}],
                   'has_arm':True,'recordings':str(recordings),'name':'Fixture Robot','ssid':'Fixture AP',
                   'pin':'87654321','wifi_password':'private-fixture-password'}
            (config_dir/'config.json').write_text(json.dumps(old))
            stdout = io.StringIO()
            with patch.object(Path,'home',return_value=home), patch.object(setup_robot.os,'geteuid',return_value=1000), \
                 patch.object(sys,'argv',['setup_robot.py','--config-dir',str(config_dir),'--skip-network','--noninteractive','--confirm-wheel-map']), \
                 patch.object(setup_robot.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'disabled','')), \
                 contextlib.redirect_stdout(stdout):
                setup_robot.main()
            new = json.loads((config_dir/'config.json').read_text())
            for field in ('pin','wifi_password','name','ssid','recordings','camera','camera_rotation','has_arm','cameras','workspace'):
                self.assertEqual(new[field],old[field],field)
            self.assertEqual(yaml.safe_load(profile_path.read_text())['lekiwi_node']['ros__parameters']['speed_tick_limit'],1234)
            self.assertEqual((recordings/'untouched').read_text(),'keep data')
            self.assertNotIn(old['pin'],stdout.getvalue())
            self.assertNotIn(old['wifi_password'],stdout.getvalue())
            card = (config_dir/'connection-card/index.html').read_text()
            self.assertNotIn(old['pin'],card)
            self.assertIn('<details>',card)
            self.assertEqual((config_dir/'config.json').stat().st_mode & 0o777,0o600)

    def test_actual_url_qr_generation_and_private_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp); config = home/'.config/lekiwi-phone'; config.mkdir(parents=True)
            (config/'config.json').write_text(json.dumps({'name':'Fixture Robot','ssid':'Fixture AP',
                                                        'pin':'DO_NOT_COPY','wifi_password':'DO_NOT_COPY'}))
            request = {'tag':'v1.2.3','commit':'a'*40}
            with patch.object(Path,'home',return_value=home), patch.object(robot_install,'verify_services'), \
                 patch.object(robot_install,'run',return_value='a'*40):
                result = robot_install.completion(ROOT, request, write_version=True)
                # A second read must not overwrite or append to the installation record.
                before = (config/'installed-version.json').read_bytes()
                again = robot_install.completion(ROOT, request)
                self.assertEqual((config/'installed-version.json').read_bytes(),before)
            svg = base64.b64decode(result['qr_svg_base64'])
            self.assertIn(b'<svg',svg)
            self.assertNotIn('DO_NOT_COPY',json.dumps(result))
            output = home/'completion.html'; install_assistant.write_completion(output,again)
            self.assertIn('data:image/svg+xml;base64,',output.read_text())
            self.assertNotIn('DO_NOT_COPY',output.read_text())

if __name__ == '__main__': unittest.main()
