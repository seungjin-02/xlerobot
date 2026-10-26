import sys,time,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from autonomy import Autonomy
from core import ControlError

class IndependentRecordingTests(unittest.TestCase):
    def setUp(self):
        backend=Mock(output_parameters={});backend.status.return_value={'available':True}
        recorder=Mock(profile={'demo':True},active=False,finishing=False,error=None)
        recorder.start.return_value='episode-test'
        self.app=SimpleNamespace(control=SimpleNamespace(backend=backend,lock=threading.RLock()),recorder=recorder)
        self.a=Autonomy(self.app,{})
        self.a.owner='owner';self.a.phase='running';self.a.thread=Mock();self.a.thread.is_alive.return_value=True
        self.a.public_limits={'max_radius_m':1.};self.a.last_report={'state':'exploring'}
        self.a.guard=Mock(fault=None);self.a.health=Mock();self.a.health.report.return_value={'ready':True}
        self.a.last_planner=time.monotonic()
    def test_driving_without_recording_is_allowed(self):
        self.a.tick()
        self.a.guard.tick.assert_called_once_with(True)
        self.a.guard.stop.assert_not_called()
        self.assertFalse(self.a.status('owner')['recording_required'])
    def test_record_tab_can_start_and_finish_without_stopping_drive(self):
        self.assertEqual(self.a.start_recording('owner','training',False),'episode-test')
        self.assertEqual(self.app.recorder.profile['control_mode'],'autonomous')
        self.assertTrue(self.a.recording_expected)
        self.a.finish_recording('owner','success')
        self.assertFalse(self.a.stop_event.is_set());self.assertFalse(self.a.recording_expected)
        self.assertEqual(self.a.phase,'running')
    def test_other_phone_cannot_start_or_finish_recording(self):
        with self.assertRaises(ControlError):self.a.start_recording('other','training')
        with self.assertRaises(ControlError):self.a.finish_recording('other','success')
        self.app.recorder.start.assert_not_called();self.app.recorder.finish.assert_not_called()
    def test_active_recording_failure_stops_drive(self):
        self.a.recording_expected=True;self.app.recorder.error='disk failure'
        self.a.tick();self.assertTrue(self.a.stop_event.is_set());self.a.guard.stop.assert_called()
    def test_return_button_requests_return_without_recording(self):
        self.a.paused=True;self.a.return_home('owner')
        self.assertTrue(self.a.return_requested);self.assertFalse(self.a.paused)
        self.app.recorder.start.assert_not_called()
        with self.assertRaises(ControlError):self.a.return_home('other')

if __name__=='__main__':unittest.main()
