import math,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from scan_filter import wheel_self_returns
class WheelReturnFilterTests(unittest.TestCase):
 def test_only_near_wheel_sectors_are_removed(self):
  values=[.14]*361;out=wheel_self_returns(values,-math.pi,math.pi/180)
  for angle in [-120,0,120]:self.assertTrue(math.isnan(out[angle+180]))
  for angle in [-180,-60,60,180]:self.assertEqual(out[angle+180],.14)
  self.assertEqual(values,[.14]*361)
 def test_far_obstacles_in_wheel_directions_remain(self):
  for value in [.17,.18,.22,.30,1.,math.inf]:
   self.assertEqual(wheel_self_returns([value],0,.1)[0],value)
 def test_invalid_cutoff_rejected(self):
  for cutoff in [0,.22,math.nan]:
   with self.assertRaises(ValueError):wheel_self_returns([1.],0,.1,cutoff)
 def test_device_angles_preserve_other_near_obstacles(self):
  values=[.14]*361;out=wheel_self_returns(values,-math.pi,math.pi/180,centers=(-60,60,180))
  for angle in [-180,-60,60,180]:self.assertTrue(math.isnan(out[angle+180]))
  for angle in [-120,0,120]:self.assertEqual(out[angle+180],.14)
  self.assertEqual(wheel_self_returns([.25],math.pi/3,.1,centers=(-60,60,180)),[.25])
 def test_invalid_device_angles_rejected(self):
  for centers in [[],[0,120],[0,120,math.nan],[0,True,120],[0,120,181],'bad']:
   with self.assertRaises(ValueError):wheel_self_returns([1.],0,.1,centers=centers)
 def test_manufacturer_profile_is_opt_in_and_preserves_farther_obstacles(self):
  values=[.14,.18,.19,.22,1.]
  self.assertEqual(wheel_self_returns(values,math.pi/3,.001),values)
  out=wheel_self_returns(values,math.pi/3,.001,self_radius=.19)
  self.assertTrue(math.isnan(out[0]) and math.isnan(out[1]))
  self.assertEqual(out[2:],values[2:]);self.assertEqual(values,[.14,.18,.19,.22,1.])
  for value in [.20,-.01,math.nan,True]:
   with self.assertRaises(ValueError):wheel_self_returns([1.],0,.1,self_radius=value)
 def test_nan_zero_and_outside_sector_preserved(self):
  out=wheel_self_returns([math.nan,0,-1],0,.001)
  self.assertTrue(math.isnan(out[0]));self.assertEqual(out[1:],[0,-1])
if __name__=='__main__':unittest.main()
