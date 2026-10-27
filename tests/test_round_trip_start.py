import threading,sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from autonomy import Autonomy
class RoundTripStartTests(unittest.TestCase):
 def app(self):
  backend=Mock(output_parameters={})
  app=SimpleNamespace(control=SimpleNamespace(backend=backend,owner=None,lock=threading.RLock()),recorder=SimpleNamespace(active=False,finishing=False))
  config={'patrol':{'calibration':{'measured':True,'robot_radius':.22,'lidar_transform':dict(x=0.,y=0.,z=.025,roll=0.,pitch=0.,yaw=0.)}}}
  return Autonomy(app,config)
 def test_round_trip_uses_bounded_distance_and_nav2_mission(self):
  a=self.app()
  with patch('autonomy.threading.Thread') as thread:
   a.start('owner',{'mode':'round_trip','target_distance':1.,'max_radius':1.5,'speed_multiplier':1})
   thread.return_value.start.assert_called_once()
  self.assertEqual(a.mission.round_trip_distance,1.);self.assertEqual(a.mission.limits.max_distance,2.4)
  self.assertEqual(a.public_limits['max_linear_m_s'],.03);a.backend.arm.assert_not_called();a.backend.publish.assert_not_called()
 def test_scan_rotation_requires_explicit_clearance(self):
  for data in [{'initial_scan_rotation':True},{'initial_scan_rotation':'true'},{'initial_scan_rotation':True,'rotation_clearance_confirmed':1}]:
   a=self.app()
   with patch('autonomy.threading.Thread') as thread:
    with self.assertRaises(ValueError):a.start('owner',data)
    thread.assert_not_called()
  a=self.app()
  with patch('autonomy.threading.Thread'):
   a.start('owner',{'initial_scan_rotation':True,'rotation_clearance_confirmed':True})
  self.assertTrue(a.initial_scan_rotation);a.backend.arm.assert_not_called()
 def test_invalid_mode_distance_or_radius_never_starts_thread(self):
  for body in [{'mode':'bad'},{'mode':'round_trip','target_distance':True},{'mode':'round_trip','target_distance':1.1},{'mode':'round_trip','max_radius':1.}]:
   a=self.app()
   with patch('autonomy.threading.Thread') as thread:
    with self.assertRaises(ValueError):a.start('owner',body)
    thread.assert_not_called()
   a.backend.arm.assert_not_called()
 def test_patrol_default_is_preserved(self):
  a=self.app()
  with patch('autonomy.threading.Thread'):a.start('owner',{})
  self.assertIsNone(a.mission.round_trip_distance);self.assertEqual(a.mission.limits.max_distance,50.)
if __name__=='__main__':unittest.main()
