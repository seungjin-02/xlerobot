import sys,unittest,math
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'app'),str(Path(__file__).resolve().parent)]
from patrol import Mission,Limits
from test_patrol import room

class WheelDistanceTests(unittest.TestCase):
 def mission(self):return Mission(Limits(.1,max_distance=2.))
 def test_map_correction_does_not_consume_travel_budget(self):
  m=self.mission();m.step(room(now=0.),(1.,1.,0.),0.,travel_distance=5.)
  m.step(room(now=1.),(1.03,1.02,0.),1.,travel_distance=5.)
  self.assertEqual(m.distance,0.);self.assertGreater(m.report()['map_distance_m'],0.)
  self.assertEqual(m.report()['distance_source'],'wheel_odometry')
 def test_real_wheel_distance_still_triggers_limit(self):
  m=self.mission();m.step(room(now=0.),(1.,1.,0.),0.,travel_distance=5.)
  m.step(room(now=1.),(1.2,1.,0.),1.,travel_distance=7.1)
  self.assertEqual(m.reason,'distance_limit')
 def test_regression_and_invalid_feedback_stop(self):
  for value,reason in [(4.9,'odometry_distance_regression'),(-1.,'invalid_travel_distance'),(math.nan,'invalid_travel_distance')]:
   m=self.mission();m.step(room(now=0.),(1.,1.,0.),0.,travel_distance=5.)
   m.step(room(now=1.),(1.,1.,0.),1.,travel_distance=value)
   self.assertEqual(m.state,'fault');self.assertEqual(m.reason,reason)
 def test_legacy_map_distance_remains_available(self):
  m=self.mission();m.step(room(now=0.),(1.,1.,0.),0.)
  m.step(room(now=1.),(1.1,1.,0.),1.)
  self.assertAlmostEqual(m.distance,.1)

if __name__=='__main__':unittest.main()
