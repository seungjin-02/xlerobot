import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'app'),str(Path(__file__).resolve().parent)]
from patrol import Mission,Limits
from test_patrol import room
from test_slam import Backend
from navigation_guard import NavigationGuard
import test_round_trip_start as start_fixtures

class StraightModeTests(unittest.TestCase):
 def test_forbidden_motion_never_reaches_motor(self):
  for motion in [(.03,.001,0.),(.03,0.,.001)]:
   backend=Backend();guard=NavigationGuard(backend)
   guard.receive(motion,straight=True);guard.tick()
   self.assertIsNotNone(guard.fault);self.assertEqual(backend.arms,0)
   self.assertEqual(backend.output,(0.,0.,0.))
 def test_forbidden_motion_disarms_an_active_motor(self):
  backend=Backend();guard=NavigationGuard(backend);guard.receive((.03,0.,0.),straight=True);guard.tick()
  self.assertTrue(backend.ready)
  guard.receive((0.,0.,.01),straight=True)
  self.assertFalse(backend.ready);self.assertEqual(backend.output,(0.,0.,0.))
 def test_straight_mode_rejects_initial_rotation_without_starting_thread(self):
  a=start_fixtures.RoundTripStartTests().app()
  with patch('autonomy.threading.Thread') as thread:
   with self.assertRaises(ValueError):a.start('owner',{'mode':'straight_round_trip','initial_scan_rotation':True,'rotation_clearance_confirmed':True})
   thread.assert_not_called()
 def test_straight_mode_has_zero_angular_limit(self):
  a=start_fixtures.RoundTripStartTests().app()
  with patch('autonomy.threading.Thread'):a.start('owner',{'mode':'straight_round_trip','target_distance':.2})
  self.assertTrue(a.mission.straight);self.assertEqual(a.public_limits['max_angular_rad_s'],0.)
  self.assertEqual(a.speed_multiplier,1);a.backend.arm.assert_not_called()
 def test_heading_or_lateral_drift_cancels(self):
  for position,reason in [((2.1,2.,.06),'straight_heading_limit'),((2.1,2.04,0.),'round_trip_lateral_limit')]:
   m=Mission(Limits(.1,max_radius=4.),.8,straight=True);m.step(room(),(2.,2.,0.),0.)
   result=m.step(room(now=1.),position,1.)
   self.assertEqual(result['action'],'cancel');self.assertEqual(m.reason,reason)
 def test_return_goal_preserves_forward_heading(self):
  m=Mission(Limits(.1,max_radius=4.),.8,straight=True);out=m.step(room(),(2.,2.,0.),0.)
  m.step(room(now=1.),(2.8,2.,0.),1.);m.result(out['token'],'succeeded')
  back=m.step(room(now=2.),(2.8,2.,0.),2.)
  self.assertEqual(back['goal'].kind,'return');self.assertEqual(back['goal'].yaw,0.)
  self.assertEqual(back['goal'].x,2.)

if __name__=='__main__':unittest.main()
