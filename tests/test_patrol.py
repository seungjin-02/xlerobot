import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from patrol import Grid, Limits, Mission, Planner
from autonomy import calibration


def room(width=40,height=40,unknown=False,now=0.):
    data=[-1 if unknown and x>25 else (100 if x in (0,width-1) or y in (0,height-1) else 0)
          for y in range(height) for x in range(width)]
    return Grid(width,height,.1,tuple(data),received_at=now)


class PlannerTests(unittest.TestCase):
    def setUp(self): self.limits=Limits(.1,margin=.02,max_radius=4.)

    def test_reject_invalid_map_or_limit(self):
        for kwargs in [{'width':True},{'resolution':float('nan')},{'data':[-2]*1600}]:
            values=dict(width=40,height=40,resolution=.1,data=(0,)*1600);values.update(kwargs)
            with self.assertRaises(ValueError):Grid(**values)
        for kwargs in [{'cycles':True},{'max_duration':0},{'robot_radius':float('inf')},{'margin':-1}]:
            values={'robot_radius':.1};values.update(kwargs)
            with self.assertRaises(ValueError):Limits(**values)

    def test_calibration_cannot_be_inferred_from_lidar_diameter(self):
        with self.assertRaises(ValueError):calibration({'patrol':{'lidar_diameter':.035}})
        with self.assertRaises(ValueError):calibration({'patrol':{'calibration':{'measured':True,'robot_radius':.2}}})
        measured={'measured':True,'robot_radius':.2,'lidar_transform':dict(x=0.,y=0.,z=.05,roll=0.,pitch=0.,yaw=0.),'pin':'not-forwarded'}
        result=calibration({'patrol':{'calibration':measured}})
        self.assertNotIn('pin',result)
        measured['robot_radius']=True
        with self.assertRaises(ValueError):calibration({'patrol':{'calibration':measured}})

    def test_rotated_origin_round_trip(self):
        g=Grid(10,10,.1,(0,)*100,origin_x=-2,origin_y=4,origin_yaw=math.pi/2)
        for i in range(100):self.assertEqual(g.cell(*g.world(i)),i)
        self.assertIsNone(g.cell(100,100))

    def test_exploration_goal_and_entire_path_are_observed_free(self):
        g=room(unknown=True);p=Planner(g,(1.,2.,0.),(1.,2.),self.limits)
        goal=p.select([(1.,2.)],[])
        self.assertEqual(goal.kind,'explore')
        for point in goal.path:
            i=g.cell(*point);self.assertIn(i,p.safe);self.assertEqual(g.data[i],0)
        self.assertLess(goal.x,2.6)

    def test_wall_separates_unreachable_room(self):
        g=room();values=list(g.data)
        for row in range(40):values[row*40+20]=100
        g=Grid(40,40,.1,tuple(values));p=Planner(g,(1.,2.,0.),(1.,2.),self.limits)
        self.assertTrue(p.parents)
        self.assertTrue(all(g.world(i)[0]<2 for i in p.parents))

    def test_full_map_uses_patrol_goal(self):
        goal=Planner(room(),(2.,2.,0.),(2.,2.),self.limits).select([(2.,2.)],[])
        self.assertEqual(goal.kind,'patrol')

    def test_footprint_stays_inside_radius(self):
        limits=Limits(.1,margin=.05,max_radius=.8)
        p=Planner(room(),(2.,2.,0.),(2.,2.),limits)
        self.assertTrue(all(math.dist(p.grid.world(i),(2.,2.))+.15<=.8 for i in p.safe))

    def test_unknown_is_not_treated_as_free(self):
        g=Grid(40,40,.1,(-1,)*1600)
        self.assertFalse(Planner(g,(2.,2.,0.),(2.,2.),self.limits).parents)


class MissionTests(unittest.TestCase):
    def mission(self,**kwargs):return Mission(Limits(.1,max_radius=4.,**kwargs))

    def test_pause_cancel_ack_resume_and_stale_result(self):
        m=self.mission();send=m.step(room(),(2.,2.,0.),0.)
        self.assertEqual(send['action'],'send_goal')
        token=send['token'];self.assertEqual(m.pause(.1)['action'],'cancel')
        self.assertFalse(m.resume());self.assertFalse(m.result(token+1,'succeeded'))
        self.assertTrue(m.result(token,'canceled'));self.assertEqual(m.state,'paused')
        self.assertTrue(m.resume());self.assertEqual(m.step(room(now=.2),(2.,2.,0.),.2)['action'],'send_goal')
        self.assertFalse(m.result(token,'succeeded'))

    def test_stale_map_cancels_and_latches_fault(self):
        m=self.mission();send=m.step(room(),(2.,2.,0.),0.)
        self.assertEqual(m.step(room(),(2.,2.,0.),6.)['action'],'cancel')
        m.result(send['token'],'canceled')
        self.assertEqual(m.state,'fault');self.assertFalse(m.resume())
        self.assertEqual(m.step(room(now=7.),(2.,2.,0.),7.)['action'],'wait')

    def test_pose_stale_or_future_is_rejected(self):
        for received in (-2.,2.):
            m=self.mission();m.step(room(),(2.,2.,0.),0.,pose_received_at=received)
            self.assertEqual(m.state,'fault')

    def test_clock_regression(self):
        m=self.mission();m.step(room(now=1.),(2.,2.,0.),1.)
        m.step(room(),(2.,2.,0.),0.);self.assertEqual(m.reason,'clock_regression')

    def test_obstacle_appears_on_active_path(self):
        m=self.mission();send=m.step(room(),(2.,2.,0.),0.)
        values=list(room().data);values[room().cell(send['goal'].x,send['goal'].y)]=100
        changed=Grid(40,40,.1,tuple(values),received_at=1.)
        self.assertEqual(m.step(changed,(2.,2.,0.),1.)['action'],'cancel')
        self.assertEqual(m.reason,'active_path_changed')

    def test_goal_timeout_cancels_before_replanning(self):
        m=self.mission(goal_timeout=1.);first=m.step(room(),(2.,2.,0.),0.)
        self.assertEqual(m.step(room(now=2.),(2.,2.,0.),2.)['action'],'cancel')
        self.assertEqual(m.step(room(now=2.1),(2.,2.,0.),2.1)['action'],'wait')
        m.result(first['token'],'canceled')
        second=m.step(room(now=2.2),(2.,2.,0.),2.2)
        self.assertNotEqual((first['goal'].x,first['goal'].y),(second['goal'].x,second['goal'].y))

    def test_cancellation_without_ack_is_fault(self):
        m=self.mission();m.step(room(),(2.,2.,0.),0.);m.stop(.1)
        self.assertEqual(m.step(room(now=4.2),(2.,2.,0.),4.2)['action'],'stop')
        self.assertEqual(m.reason,'cancel_ack_timeout')

    def test_failed_goal_is_not_reissued(self):
        m=self.mission();first=m.step(room(),(2.,2.,0.),0.)
        m.result(first['token'],'failed');second=m.step(room(now=1.),(2.,2.,0.),1.)
        self.assertNotEqual((first['goal'].x,first['goal'].y),(second['goal'].x,second['goal'].y))

    def test_duration_returns_home_instead_of_new_exploration(self):
        m=self.mission(max_duration=1.);send=m.step(room(),(2.,2.,0.),0.)
        m.step(room(now=2.),(2.4,2.,0.),2.)
        m.result(send['token'],'canceled')
        result=m.step(room(now=2.1),(2.4,2.,0.),2.1)
        self.assertEqual(result['goal'].kind,'return')

    def test_distance_limit_stops(self):
        m=self.mission(max_distance=.9);m.step(room(),(2.,2.,0.),0.)
        m.step(room(now=1.),(2.95,2.,0.),1.);self.assertEqual(m.reason,'distance_limit')

    def test_pose_jump_fault(self):
        m=self.mission();m.step(room(),(2.,2.,0.),0.)
        m.step(room(now=1.),(3.5,2.,0.),1.);self.assertEqual(m.reason,'localization_jump')

    def test_operator_stop_does_not_resume(self):
        m=self.mission();m.stop(0.);self.assertFalse(m.resume())
        self.assertEqual(m.step(room(),(2.,2.,0.),0.)['action'],'wait')


if __name__=='__main__':unittest.main()
