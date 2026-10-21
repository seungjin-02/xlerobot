import copy
import json
import math
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace as N
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'));sys.path.insert(0,str(ROOT/'tools'))
from slam import configuration, SensorHealth, SlamSession, atomic_json
from recorder import EpisodeRecorder
from navigation_guard import NavigationGuard
from slam_map import save_grid
from start_navigation import parameters


def stamp(sec=10): return N(sec=sec,nanosec=0)
def vector(x=0.,y=0.,z=0.): return N(x=x,y=y,z=z)
def rotation(): return N(x=0.,y=0.,z=0.,w=1.)
def transform(parent,child):
    return N(header=N(frame_id=parent,stamp=stamp()),child_frame_id=child,
             transform=N(translation=vector(),rotation=rotation()))
def scan():
    return N(header=N(frame_id='laser',stamp=stamp()),ranges=[1.,2.,float('inf')],
             range_min=.05,range_max=10.,angle_increment=.1,angle_min=0.,angle_max=.2,scan_time=.1,time_increment=0.)
def odom():
    return N(header=N(frame_id='odom',stamp=stamp()),child_frame_id='base_footprint',
             pose=N(pose=N(position=vector(),orientation=rotation())),twist=N(twist=N(linear=vector(),angular=vector())))


class HealthTests(unittest.TestCase):
    def healthy(self):
        health=SensorHealth(configuration())
        health.observe('/scan',scan(),0);health.observe('/odom',odom(),0)
        health.observe('/tf',N(transforms=[transform('odom','base_footprint')]),0)
        health.observe('/tf_static',N(transforms=[transform('base_footprint','laser')]),0)
        return health

    def test_requires_actual_scan_odom_and_connected_tf(self):
        health=SensorHealth(configuration());self.assertFalse(health.report()['ready'])
        health.observe('/scan',scan(),0);health.observe('/odom',odom(),0)
        self.assertFalse(health.report()['ready'])
        health.observe('/tf',N(transforms=[transform('odom','base_footprint')]),0)
        self.assertFalse(health.report()['ready'])
        health.observe('/tf_static',N(transforms=[transform('base_footprint','laser')]),0)
        self.assertTrue(health.report(1)['ready'])

    def test_stale_dynamic_transforms_and_scan_not_reported_ready(self):
        health=self.healthy();self.assertFalse(health.report(3)['ready'])
        self.assertTrue(health.connected('base_footprint','laser',now=3))
        self.assertFalse(health.connected('odom','base_footprint',now=3))

    def test_lidar_infinity_allowed_but_no_return_or_bad_geometry_fails(self):
        self.assertTrue(self.healthy().report()['ready'])
        for changes in ({'ranges':[float('nan'),float('inf')]},{'angle_increment':0.},{'angle_min':float('nan')}):
            health=self.healthy();value=scan()
            for key,item in changes.items():setattr(value,key,item)
            health.observe('/scan',value,1)
            self.assertFalse(health.report()['ready'])

    def test_wrong_frames_and_clock_reversal_are_reported(self):
        health=self.healthy();message=odom();message.child_frame_id='unknown';health.observe('/odom',message,1)
        self.assertFalse(health.report()['ready'])
        health=self.healthy();message=scan();message.header.stamp=stamp(9);health.observe('/scan',message,1)
        self.assertEqual(health.report()['clock_regressions'],1)

    def test_invalid_quaternion_fails_quality(self):
        health=self.healthy();value=transform('base_footprint','camera');value.transform.rotation.w=0.
        health.observe('/tf_static',N(transforms=[value]),1)
        self.assertFalse(health.report()['ready'])

    def test_sensor_clock_offset_and_zero_dynamic_tf_rejected(self):
        health=self.healthy();message=scan();message.header.stamp=stamp(20);health.observe('/scan',message,1)
        self.assertFalse(health.report()['ready'])
        self.assertIn('scan/odom 시각 차이 1초 초과',health.report()['missing'])
        health=self.healthy();value=transform('odom','base_footprint');value.header.stamp=stamp(0)
        health.observe('/tf',N(transforms=[value]),1);self.assertFalse(health.report()['ready'])

    def test_custom_topics_and_unavailable_optional_topics(self):
        config=configuration({'scan_topic':'/lidar/scan','base_frame':'base_link'})
        self.assertEqual(config['topics']['/lidar/scan'],'sensor_msgs/msg/LaserScan')
        self.assertEqual(config['base_frame'],'base_link')
        self.assertTrue(self.healthy().report()['ready']) # Optional IMU/joints not required.
        for options in ({'scan_topic':'/tf'},{'scan_topic':'/scan;rm'},{'base_frame':'/base'},
                        {'extra_topics':{'/password':'unknown/Secret'}}):
            with self.assertRaises(ValueError):configuration(options)


class NoCamera:
    frame=None;error='no camera'
    def start(self): pass
    def close(self): pass


class Session:
    def __init__(self,config):self.config=config;self.fail=False
    def start(self,episode):
        folder=Path(episode)/'slam';folder.mkdir()
    def status(self):return {'ready':not self.fail,'bag_closed':False,'missing':[] if not self.fail else ['scan']}
    def stop(self):return {'ready':not self.fail,'bag_closed':True,'complete':True,'counts':{'/scan':20}}


class RecorderTests(unittest.TestCase):
    def test_worker_premature_clean_exit_is_not_treated_as_full_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);atomic_json(folder/'status.json',{'ready':True,'bag_closed':True,'error':None})
            session=SlamSession(configuration());session.folder=folder
            session.process=Mock();session.process.poll.return_value=0;session.process.returncode=0
            self.assertFalse(session.status()['ready'])
            self.assertFalse(session.stop()['complete'])

    def test_slam_only_capture_does_not_require_or_invent_camera_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            recorder=EpisodeRecorder(tmp,feed=NoCamera(),slam_supported=True,slam_factory=Session)
            recorder.start('phone','SLAM room',slam=True)
            recorder.sample((0.,0.,0.),(0.,0.,0.),None,False,0,True)
            result=recorder.finish('phone','success')
            meta=json.loads((recorder.path/'episode.json').read_text())
            self.assertTrue(meta['complete']);self.assertTrue(meta['slam']['valid_for_mapping'])
            self.assertEqual(meta['format'],'lekiwi-episode-v1')
            self.assertEqual(result['valid_samples'],0)
            self.assertTrue((recorder.path/'slam/manifest.json').exists())
            self.assertEqual(list((recorder.path/'frames').iterdir()),[])
            recorder.close()

    def test_demo_rejects_sensor_recording(self):
        with tempfile.TemporaryDirectory() as tmp:
            recorder=EpisodeRecorder(tmp,feed=NoCamera())
            with self.assertRaises(ValueError):recorder.start('phone','demo',slam=True)
            with self.assertRaises(ValueError):recorder.start('phone','demo',slam='yes')
            recorder.close()

    def test_sensor_failure_marks_incomplete_and_preserves_recording(self):
        with tempfile.TemporaryDirectory() as tmp:
            recorder=EpisodeRecorder(tmp,feed=NoCamera(),slam_supported=True,slam_factory=Session)
            recorder.start('phone','sensor failure',slam=True);recorder.slam.fail=True
            recorder.sample((0.,0.,0.),(0.,0.,0.),None,False,0,True)
            recorder.finish('phone','success')
            meta=json.loads((recorder.path/'episode.json').read_text())
            self.assertFalse(meta['complete']);self.assertFalse(meta['slam']['valid_for_mapping'])
            self.assertEqual(meta['outcome'],'interrupted')
            recorder.close()


class Backend:
    def __init__(self):self.output=(0.,0.,0.);self.ready=False;self.others=0;self.arms=0;self.available=True
    def arm(self):self.ready=True;self.arms+=1
    def disarm(self):self.ready=False
    def status(self):return {'available':self.available,'motor_ready':self.ready,'other_publishers':self.others}
    def publish(self,value):self.output=value;return value
    def limit_motion(self,value):return value


class GuardTests(unittest.TestCase):
    def setUp(self):self.now=0.;self.backend=Backend();self.guard=NavigationGuard(self.backend,clock=lambda:self.now)
    def test_never_arms_without_goal_and_bounds_omni_commands(self):
        self.guard.tick();self.assertEqual(self.backend.arms,0)
        self.guard.receive((1.,1.,2.));self.now=.05;self.guard.tick()
        self.assertLessEqual(math.hypot(*self.guard.command[:2]),.1000001)
        self.assertLessEqual(abs(self.guard.command[2]),.5)
        self.assertLessEqual(math.hypot(*self.backend.output[:2]),.0100001)

    def test_timeout_disarms_and_latches_until_restart(self):
        self.guard.receive((.1,0.,0.));self.now=.05;self.guard.tick()
        self.now=.4;self.guard.tick();self.assertFalse(self.backend.ready)
        self.assertEqual(self.backend.output,(0.,0.,0.))
        self.guard.receive((.1,0.,0.));self.guard.tick();self.assertEqual(self.backend.arms,1)

    def test_sensor_loss_or_other_controller_disarms(self):
        for failure in ('sensor','publisher','connection'):
            self.setUp();self.guard.receive((.1,0.,0.));self.now=.05;self.guard.tick()
            if failure=='publisher':self.backend.others=1
            if failure=='connection':self.backend.available=False
            self.guard.tick(sensors_ready=failure!='sensor')
            self.assertFalse(self.backend.ready);self.assertIsNotNone(self.guard.fault)

    def test_zero_stops_without_slew_and_nonfinite_never_arms(self):
        self.guard.receive((.1,0.,0.));self.now=.05;self.guard.tick()
        self.guard.receive((0.,0.,0.));self.guard.tick();self.assertEqual(self.backend.output,(0.,0.,0.));self.assertFalse(self.backend.ready)
        self.guard.receive((float('nan'),0.,0.));self.guard.tick();self.assertIsNotNone(self.guard.fault)

    def test_failed_arm_always_attempts_disarm(self):
        def fail():self.backend.ready=True;raise RuntimeError('after power on')
        self.backend.arm=fail;self.guard.receive((.1,0.,0.));self.guard.tick()
        self.assertFalse(self.backend.ready)


class MapTests(unittest.TestCase):
    def test_grid_export_flips_rows_and_preserves_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            message=N(info=N(width=2,height=2,resolution=.05,origin=N(position=vector(),orientation=rotation())),data=[0,100,-1,0])
            save_grid(message,tmp)
            self.assertTrue((Path(tmp)/'map.pgm').read_bytes().endswith(bytes([205,254,254,0])))
            import yaml
            metadata=yaml.safe_load((Path(tmp)/'map.yaml').read_text());self.assertEqual(metadata['free_thresh'],.196)

    def test_unknown_only_map_is_not_navigation_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):save_grid(N(info=N(width=2,height=2,resolution=.05),data=[-1]*4),tmp)

    def test_nav2_parameters_use_omni_controller_and_explicit_footprint(self):
        template={key:{'ros__parameters':{}} for key in ('amcl','map_server','bt_navigator','behavior_server','controller_server')}
        template['controller_server']['ros__parameters']={'general_goal_checker':{},'FollowPath':{'plugin':'nav2_mppi_controller::MPPIController'}}
        for key in ('local_costmap','global_costmap'):template[key]={key:{'ros__parameters':{'voxel_layer':{'scan':{'topic':'scan'}}}}}
        result=parameters(template,Path('/tmp/map.yaml'),.25,configuration())
        self.assertEqual(result['amcl']['ros__parameters']['robot_model_type'],'nav2_amcl::OmniMotionModel')
        plugin=result['controller_server']['ros__parameters']['FollowPath']
        self.assertEqual(plugin['plugin'],'dwb_core::DWBLocalPlanner');self.assertGreater(plugin['max_vel_y'],0.)
        self.assertIn('BaseObstacle',plugin['critics'])
        self.assertEqual(result['local_costmap']['local_costmap']['ros__parameters']['robot_radius'],.25)
        template.pop('map_server')
        self.assertEqual(parameters(template,Path('/tmp/map.yaml'),.25,configuration())['map_server']['ros__parameters']['yaml_filename'],'/tmp/map.yaml')
        with self.assertRaises(ValueError):parameters(template,Path('/tmp/map.yaml'),float('nan'),configuration())


if __name__=='__main__':unittest.main()
