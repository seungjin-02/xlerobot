import sys,time,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from autonomy import Autonomy,calibration
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
        self.a.guard=Mock(fault=None,output=(0.,0.,0.));self.a.health=Mock();self.a.health.report.return_value={'ready':True}
        self.a.last_planner=time.monotonic()
    def test_confirmed_bound_preserves_estimated_pose_provenance(self):
        value={'measured':False,'geometry_mode':'confirmed_conservative_envelope',
            'envelope_confirmed':True,'stationary_sensor_test_passed':True,
            'lidar_pose_source':'installed_urdf_stationary_verified','robot_radius':.22,
            'lidar_transform':dict(x=0.,y=0.,z=.025384,roll=3.14159265359,pitch=0.,yaw=0.)}
        result=calibration({'patrol':{'calibration':value}})
        self.assertEqual(result['geometry_mode'],'confirmed_conservative_envelope')
        for key in ['envelope_confirmed','stationary_sensor_test_passed','lidar_pose_source']:
            bad=dict(value);bad.pop(key)
            with self.assertRaises(ValueError):calibration({'patrol':{'calibration':bad}})

    def test_speed_change_is_owned_and_recorded_without_stopping_drive(self):
        self.a.set_speed('owner',1)
        self.a.guard.set_limits.assert_called_once_with(.03,.15)
        self.assertEqual(self.a.public_limits['max_linear_m_s'],.03)
        self.assertFalse(self.a.stop_event.is_set())
        with self.assertRaises(ControlError):self.a.set_speed('other',2)
        for value in [True,0,4,30,1.5]:
            with self.assertRaises(ValueError):self.a.set_speed('owner',value)

    def test_driving_without_recording_is_allowed(self):
        self.a.tick()
        self.a.guard.tick.assert_called_once_with(True)
        self.a.guard.stop.assert_not_called()
        self.assertFalse(self.a.status('owner')['recording_required'])
    def test_status_reports_navigation_guard_output(self):
        self.a.guard.output=(.02,-.01,.05)
        self.assertEqual(self.a.status('owner')['output_motion'],[.02,-.01,.05])
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
