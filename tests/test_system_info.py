import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
import system_info


class DiagnosticsTests(unittest.TestCase):
    def test_missing_git_and_service_manager_are_unknown(self):
        with patch.object(system_info,'output',return_value=None):
            self.assertEqual(system_info.git_version(ROOT), {'commit':None,'tag':None,'modified':None})
            self.assertEqual(system_info.service_state('lekiwi-camera.service'), {'state':'unknown'})

    def test_not_found_service_is_not_reported_healthy(self):
        with patch.object(system_info,'output',return_value='LoadState=not-found\nActiveState=inactive\nSubState=dead'):
            value=system_info.service_state('lekiwi-camera.service')
        self.assertEqual(value['state'],'inactive');self.assertEqual(value['load'],'not-found')

    def test_missing_recordings_uses_containing_filesystem(self):
        with tempfile.TemporaryDirectory() as tmp:
            value=system_info.storage_info(Path(tmp)/'new'/'recordings')
            self.assertGreater(value['free_bytes'],256*1024**2)
            self.assertFalse((Path(tmp)/'new').exists())

    def test_unavailable_ros_never_reports_stale_ready_as_fresh_feedback(self):
        control={'available':False,'motor_ready':True,'armed':False}
        with patch.object(system_info,'git_version',return_value={}), patch.object(system_info,'service_state',return_value={'state':'unknown'}):
            value=system_info.SystemInfo(ROOT,ROOT/'private/recordings').snapshot(control,'Fixture',None)
        self.assertIsNone(value['motor']['feedback_ready'])
        self.assertFalse(value['motor']['feedback_fresh'])
        self.assertFalse(value['motor']['physical_stop_verified'])


if __name__ == '__main__': unittest.main()
