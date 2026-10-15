import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import workspace_path
import verify_robot
from robot_install import InstallError


class WorkspaceTests(unittest.TestCase):
    def test_existing_custom_workspace_is_resolved_with_spaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'robot config'
            config.mkdir()
            workspace = Path(tmp) / 'custom ros workspace'
            (config / 'config.json').write_text(json.dumps({'workspace': str(workspace)}))
            before = (config / 'config.json').read_bytes()
            actual = subprocess.check_output([sys.executable, str(ROOT/'tools/workspace_path.py'),
                '--config-dir', str(config)], text=True).strip()
            self.assertEqual(actual, str(workspace))
            self.assertEqual((config/'config.json').read_bytes(), before)
            self.assertFalse(workspace.exists())

    def test_explicit_workspace_overrides_existing_setting(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp)
            (config/'config.json').write_text('{broken private config')
            target = config / 'replacement'
            self.assertEqual(workspace_path.workspace_path(config, str(target)), target)

    def test_new_install_uses_default_and_expands_home(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(Path, 'home', return_value=Path(tmp)):
            self.assertEqual(workspace_path.workspace_path(Path(tmp)/'missing'),
                Path(tmp)/'.local/share/lekiwi-phone/ros_ws')

    def test_corrupt_or_empty_existing_setting_fails_without_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp)
            for value in ('{broken', '[]', '{"workspace":""}', '{"workspace":42}'):
                (config/'config.json').write_text(value)
                with self.subTest(value=value), self.assertRaises(ValueError):
                    workspace_path.workspace_path(config)
                self.assertEqual((config/'config.json').read_text(), value)


class IdlePreconditionsTests(unittest.TestCase):
    def setUp(self):
        self.status = {'armed': False, 'motor_ready': None, 'available': False,
            'other_publishers': 0, 'recording': {'active': False, 'finishing': False}}

    def test_software_idle_with_unknown_motor_feedback_is_not_physical_verification(self):
        verify_robot.validate_idle_status(self.status)
        self.assertIsNone(self.status['motor_ready'])
        self.assertFalse(self.status['available'])

    def test_each_missing_status_field_blocks_update_check(self):
        for key in self.status:
            partial = {k: v for k, v in self.status.items() if k != key}
            with self.subTest(key=key), self.assertRaises(InstallError):
                verify_robot.validate_idle_status(partial)
        for recording in ({}, {'active': False}, {'active': 'false', 'finishing': False}):
            with self.assertRaises(InstallError):
                verify_robot.validate_idle_status({**self.status, 'recording': recording})

    def test_active_control_recording_or_other_publisher_blocks_update_check(self):
        for key in ('armed', 'motor_ready', 'other_publishers'):
            with self.subTest(key=key), self.assertRaises(InstallError):
                verify_robot.validate_idle_status({**self.status, key: 1 if key == 'other_publishers' else True})
        for key in ('active', 'finishing'):
            with self.assertRaises(InstallError):
                verify_robot.validate_idle_status({**self.status, 'recording': {**self.status['recording'], key: True}})

    def test_malformed_status_is_not_idle(self):
        for status in (None, [], {}, {**self.status, 'armed': 0},
                {**self.status, 'other_publishers': -1}, {**self.status, 'other_publishers': False}):
            with self.subTest(status=status), self.assertRaises(InstallError):
                verify_robot.validate_idle_status(status)


if __name__ == '__main__':
    unittest.main()
