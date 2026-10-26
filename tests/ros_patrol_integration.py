#!/usr/bin/env python3
"""Full web runtime: online SLAM + Nav2 + autonomous goals + raw bag, fake motor.

Uses synthetic room rays and perfect odometry, not a physics engine or real robot.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'app'),str(ROOT/'tests')]
from server import App
from maintenance import Maintenance
from ros_slam_integration import Room
from ros_navigation_integration import FakeMotor


def run(output):
    os.environ['ROS_DOMAIN_ID']='185';os.environ['ROS_AUTOMATIC_DISCOVERY_RANGE']='LOCALHOST'
    import rclpy
    rclpy.init()
    class Backend(FakeMotor):
        def __init__(self):
            super().__init__();self.node=rclpy.create_node('synthetic_patrol_backend')
            self.output_parameters={'demo':True,'base_frame':'base_footprint','odom_frame':'odom'}
        def poll(self):rclpy.spin_once(self.node,timeout_sec=0)
        def _ensure_base(self):pass
        def observation(self):return {'received_ns':time.monotonic_ns(),'ros_stamp_ns':self.node.get_clock().now().nanoseconds,'values':[*room.position,*self.output]}
    backend=Backend();room=Room(backend.node,backend)
    output.mkdir(parents=True,exist_ok=False)
    config={'name':'SYNTHETIC PATROL TEST','recordings':str(output/'episodes'),
        'patrol':{'calibration':{'measured':True,'robot_radius':.2,'lidar_frame':'laser','external_lidar_tf':True,
                    'lidar_transform':dict(x=.1,y=0.,z=0.,roll=0.,pitch=0.,yaw=0.)}}}
    app=App(backend,'synthetic-only',config);app.maintenance=Maintenance(output/'maintenance',required=False)
    worker=threading.Thread(target=app.run);worker.start()
    try:
        app.autonomy.start('synthetic-owner',{'max_radius':1.,'max_duration':25.,'cycles':1,'task':'synthetic online SLAM patrol'})
        ready_deadline=time.monotonic()+50
        while app.autonomy.busy and app.autonomy.phase=='starting' and time.monotonic()<ready_deadline:time.sleep(.1)
        assert app.autonomy.phase=='running',app.autonomy.status()
        assert not app.recorder.active,'Autonomy must not start recording automatically'
        app.autonomy.start_recording('synthetic-owner','synthetic explicitly selected recording',slam=True)
        deadline=time.monotonic()+110
        while app.autonomy.busy and time.monotonic()<deadline:time.sleep(.2)
        if app.autonomy.busy:raise RuntimeError('Patrol did not finish within integration deadline')
        status=app.autonomy.status('synthetic-owner')
        if status['error']:raise RuntimeError(status['error'])
        episode=output/'episodes'/status['recording_episode']
        meta=json.loads((episode/'episode.json').read_text())
        events=[json.loads(line) for line in (episode/'commands.jsonl').read_text().splitlines()]
        successful=sum(e.get('type')=='autonomy_goal_result' and e.get('outcome')=='succeeded' for e in events)
        assert meta['complete'] and meta['slam']['valid_for_mapping'],meta
        assert meta['device_profile']['control_mode']=='autonomous'
        assert successful>=1 and backend.arms>=1,(successful,backend.arms,status)
        assert not backend.ready and backend.output==(0.,0.,0.)
        assert 0<backend.peak<=.100001
        report={'synthetic':True,'physics_engine':False,'physical_hardware_tested':False,
            'online_slam_used':True,'nav2_action_goals_succeeded':successful,'mission':status['mission'],
            'episode_complete':meta['complete'],'slam_valid_for_mapping':meta['slam']['valid_for_mapping'],
            'scan_messages':meta['slam']['counts']['/scan'],'valid_visual_training_samples':meta['valid_samples'],
            'peak_guarded_linear_m_s':backend.peak,'motor_ready_after_stop':backend.ready,'output_after_stop':backend.output,
            'control_mode':meta['device_profile']['control_mode'],'outcome':meta['outcome']}
        (output/'integration-report.json').write_text(json.dumps(report,indent=2))
        print(json.dumps(report,indent=2))
    finally:
        app.autonomy.request_stop(emergency=True)
        if app.autonomy.thread:app.autonomy.thread.join(timeout=20)
        app.shutdown.set();worker.join(timeout=3);app.recorder.close();room.close()
        backend.node.destroy_node();rclpy.shutdown()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();run(a.output)
