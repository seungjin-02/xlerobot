import math,sys,unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from navigation_guard import NavigationGuard
class AutonomySpeedTests(unittest.TestCase):
 def test_new_command_is_capped_to_selected_vector_speed(self):
  b=Mock();g=NavigationGuard(b,clock=lambda:1.)
  g.set_limits(.03,.15);g.receive((.1,.1,1.))
  self.assertAlmostEqual(math.hypot(*g.command[:2]),.03);self.assertAlmostEqual(g.command[2],.15)
  b.arm.assert_not_called();b.publish.assert_not_called()
 def test_decreasing_speed_caps_output_without_refreshing_old_command(self):
  b=Mock();b.status.return_value={'available':True,'motor_ready':True,'other_publishers':0}
  clock=[1.];g=NavigationGuard(b,clock=lambda:clock[0]);g.receive((.1,0,.5))
  g.output=(.09,0,.45);g.armed=True;clock[0]=2.
  g.set_limits(.03,.15)
  self.assertEqual(g.received,1.);self.assertAlmostEqual(g.output[0],.03)
  g.tick();self.assertFalse(g.armed);self.assertEqual(g.output,(0.,0.,0.));b.disarm.assert_called()
 def test_increasing_speed_does_not_enable_motors(self):
  b=Mock();g=NavigationGuard(b);g.set_limits(.03,.15);g.set_limits(.09,.45)
  self.assertFalse(g.armed);self.assertIsNone(g.received);b.arm.assert_not_called()
 def test_unsupported_or_invalid_limits_are_rejected(self):
  for v in [0,.9,math.inf,math.nan,True]:
   with self.assertRaises(ValueError):NavigationGuard(Mock()).set_limits(v,.15)
if __name__=='__main__':unittest.main()
