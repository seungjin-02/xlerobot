import math,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from patrol import Limits,Mission,Grid
from test_patrol import room

class RoundTripTests(unittest.TestCase):
 def mission(self,distance=1.):return Mission(Limits(.1,margin=.02,max_radius=2.5,max_distance=2.4),round_trip_distance=distance)
 def grid(self,now=0.):return room(60,60,now=now)
 def test_two_navigation_goals_outbound_then_home(self):
  m=self.mission();out=m.step(self.grid(),(2.,2.,0.),0.)
  self.assertEqual(out['action'],'send_goal');self.assertEqual(out['goal'].kind,'outbound')
  self.assertEqual((out['goal'].x,out['goal'].y),(3.,2.))
  m.step(self.grid(1.),(3.,2.,0.),1.);self.assertTrue(m.result(out['token'],'succeeded'))
  back=m.step(self.grid(2.),(3.,2.,0.),2.)
  self.assertEqual(back['goal'].kind,'return');self.assertAlmostEqual(back['goal'].yaw,0.)
  self.assertEqual((back['goal'].x,back['goal'].y),(2.,2.))
  m.step(self.grid(3.),(2.,2.,0.),3.);m.result(back['token'],'succeeded')
  self.assertTrue(m.report()['round_trip_completed']);self.assertEqual(m.report()['goals_sent'],2)
 def test_goal_uses_initial_robot_heading(self):
  m=self.mission();out=m.step(self.grid(),(2.,2.,math.pi/2),0.)
  self.assertAlmostEqual(out['goal'].x,2.);self.assertAlmostEqual(out['goal'].y,3.)
 def test_failed_outbound_never_counts_as_round_trip(self):
  m=self.mission();out=m.step(self.grid(),(2.,2.,0.),0.)
  m.result(out['token'],'failed');self.assertEqual(m.state,'blocked');self.assertFalse(m.report()['round_trip_completed'])
 def test_false_success_far_from_goal_is_rejected(self):
  m=self.mission();out=m.step(self.grid(),(2.,2.,0.),0.);m.result(out['token'],'succeeded')
  self.assertFalse(m.outbound_reached);self.assertEqual(m.state,'blocked')
 def test_obstacle_or_unknown_on_corridor_blocks_goal(self):
  for value in (100,-1):
   g=self.grid();data=list(g.data);data[20*60+25]=value
   m=self.mission();out=m.step(Grid(60,60,.1,tuple(data)),(2.,2.,0.),0.)
   self.assertEqual(out['action'],'send_goal');self.assertEqual(out['goal'].kind,'outbound_stage')
   self.assertLess(out['goal'].x,2.5);self.assertFalse(m.outbound_reached)
   m.step(Grid(60,60,.1,tuple(data),received_at=1.),(out['goal'].x,out['goal'].y,0.),1.)
   m.result(out['token'],'succeeded')
   end=m.step(Grid(60,60,.1,tuple(data),received_at=2.),(out['goal'].x,out['goal'].y,0.),2.)
   self.assertEqual(end['action'],'stop');self.assertEqual(m.reason,'outbound_corridor_not_clear')
 def test_changed_path_cancels_and_does_not_replan_outside_corridor(self):
  m=self.mission();out=m.step(self.grid(),(2.,2.,0.),0.);g=self.grid(1.);data=list(g.data);data[20*60+25]=100
  cancel=m.step(Grid(60,60,.1,tuple(data),received_at=1.),(2.,2.,0.),1.)
  self.assertEqual(cancel['action'],'cancel');m.result(out['token'],'canceled');self.assertEqual(m.state,'blocked')
 def test_lateral_limit_and_overshoot_stop(self):
  m=self.mission();m.step(self.grid(),(2.,2.,0.),0.)
  self.assertEqual(m.step(self.grid(1.),(2.1,2.11,0.),1.)['action'],'cancel')
  self.assertEqual(m.reason,'round_trip_lateral_limit')
  m=self.mission();m.step(self.grid(),(2.,2.,0.),0.);m.step(self.grid(1.),(2.8,2.,0.),1.)
  m.step(self.grid(2.),(3.11,2.,0.),2.);self.assertEqual(m.reason,'round_trip_overshoot')
 def test_pause_resume_keeps_original_goal(self):
  m=self.mission();out=m.step(self.grid(),(2.,2.,0.),0.);m.pause(.1);m.result(out['token'],'canceled');self.assertTrue(m.resume())
  resumed=m.step(self.grid(1.),(2.2,2.,0.),1.);self.assertEqual(resumed['goal'].x,3.)
 def test_new_observations_allow_progress_to_original_target(self):
  g=self.grid();data=list(g.data);data[20*60+25]=-1;m=self.mission()
  stage=m.step(Grid(60,60,.1,tuple(data)),(2.,2.,0.),0.)
  position=(stage['goal'].x,stage['goal'].y,0.)
  m.step(self.grid(1.),position,1.);m.result(stage['token'],'succeeded')
  final=m.step(self.grid(2.),position,2.)
  self.assertEqual(final['goal'].kind,'outbound');self.assertEqual(final['goal'].x,3.)
  self.assertFalse(m.outbound_reached)
 def test_invalid_distance_is_rejected(self):
  for distance in [True,0,1.1,math.nan]:
   with self.assertRaises(ValueError):self.mission(distance)

if __name__=='__main__':unittest.main()
