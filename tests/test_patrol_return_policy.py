import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'app'),str(Path(__file__).resolve().parent)]
from patrol import Mission,Limits,Grid
from test_patrol import room

class PatrolReturnTests(unittest.TestCase):
 def exhausted(self):
  m=Mission(Limits(.1,max_radius=4.,cycles=3));goal=m.step(room(),(2.,2.,0.),0.)
  m.step(room(now=1.),(2.4,2.,0.),1.);m.result(goal['token'],'failed')
  return m
 def test_no_remaining_targets_returns_home_without_claiming_coverage(self):
  m=self.exhausted()
  with patch('patrol.Planner.select',return_value=None):action=m.step(room(now=2.),(2.4,2.,0.),2.)
  self.assertEqual(action['action'],'send_goal');self.assertEqual(action['goal'].kind,'return')
  self.assertEqual(m.return_reason,'reachable_targets_exhausted');self.assertEqual(m.cycles,0)
 def test_blocked_home_stops_instead_of_forcing_return(self):
  m=self.exhausted();g=room(now=2.);data=list(g.data);data[g.cell(2.,2.)]=100
  with patch('patrol.Planner.select',return_value=None):action=m.step(Grid(g.width,g.height,g.resolution,tuple(data),received_at=2.),(2.4,2.,0.),2.)
  self.assertEqual(action['action'],'stop');self.assertEqual(m.reason,'home_unreachable')
 def test_duration_return_reason_survives_navigation_completion(self):
  m=Mission(Limits(.1,max_radius=4.,max_duration=1.));out=m.step(room(),(2.,2.,0.),0.)
  m.step(room(now=2.),(2.4,2.,0.),2.);m.result(out['token'],'canceled')
  back=m.step(room(now=2.1),(2.4,2.,0.),2.1)
  self.assertEqual(back['goal'].kind,'return');self.assertEqual(m.return_reason,'duration_limit')
  m.step(room(now=2.2),(2.,2.,0.),2.2);m.result(back['token'],'succeeded')
  self.assertEqual(m.return_reason,'duration_limit')
 def test_safe_alternative_is_used_before_returning(self):
  m=self.exhausted();action=m.step(room(now=2.),(2.4,2.,0.),2.)
  self.assertEqual(action['action'],'send_goal');self.assertNotEqual(action['goal'].kind,'return')

if __name__=='__main__':unittest.main()
