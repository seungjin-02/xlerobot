#!/usr/bin/env python3
"""ROS Jazzy integration fixture: synthetic rectangular room, never hardware.

Run inside the documented ROS test container, not on a connected robot.
"""
import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app')); sys.path.insert(0,str(ROOT/'tools'))


class NoCamera:
    error = 'synthetic fixture intentionally has no camera'
    frame = None
    def start(self): pass
    def close(self): pass


class Room:
    def __init__(self, node, backend=None):
        from sensor_msgs.msg import LaserScan, Imu, JointState
        from nav_msgs.msg import Odometry
        from tf2_msgs.msg import TFMessage
        from geometry_msgs.msg import TransformStamped, Twist
        from std_msgs.msg import Bool
        from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy
        self.node,self.backend = node,backend
        self.Scan,self.Odom,self.TF,self.Transform,self.Imu,self.Joint = LaserScan,Odometry,TFMessage,TransformStamped,Imu,JointState
        self.scan = node.create_publisher(LaserScan,'/scan',10)
        self.odom = node.create_publisher(Odometry,'/odom',10)
        self.tf = node.create_publisher(TFMessage,'/tf',10)
        self.static = node.create_publisher(TFMessage,'/tf_static',QoSProfile(depth=1,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,reliability=ReliabilityPolicy.RELIABLE))
        self.imu = node.create_publisher(Imu,'/imu/data',10)
        self.joints = node.create_publisher(JointState,'/joint_states',10)
        self.command = node.create_publisher(Twist,'/cmd_vel',10) if backend is None else None
        self.motor = node.create_publisher(Bool,'/motor_ready',10) if backend is None else None
        self.Twist,self.Bool = Twist,Bool
        self.started=time.monotonic(); self.stop=threading.Event(); self.position=(0.,0.,0.)
        self.thread=threading.Thread(target=self.publish); self.thread.start()

    def publish(self):
        previous=time.monotonic()
        while not self.stop.wait(.05):
            now=time.monotonic();dt=now-previous;previous=now
            if self.backend:
                x,y,yaw=self.position;vx,vy,w=self.backend.output
                x+=(math.cos(yaw)*vx-math.sin(yaw)*vy)*dt;y+=(math.sin(yaw)*vx+math.cos(yaw)*vy)*dt;yaw+=w*dt
            else:
                elapsed=now-self.started
                x=.2*math.sin(elapsed*.4);y=0.;yaw=.08*math.sin(elapsed*.3)
            self.position=(x,y,yaw)
            stamp=self.node.get_clock().now().to_msg()
            odom=self.Odom();odom.header.stamp=stamp;odom.header.frame_id='odom';odom.child_frame_id='base_footprint'
            odom.pose.pose.position.x=x;odom.pose.pose.position.y=y
            odom.pose.pose.orientation.z=math.sin(yaw/2);odom.pose.pose.orientation.w=math.cos(yaw/2)
            if self.backend:
                odom.twist.twist.linear.x=vx;odom.twist.twist.linear.y=vy;odom.twist.twist.angular.z=w
            self.odom.publish(odom)
            dynamic=self.Transform();dynamic.header=odom.header;dynamic.child_frame_id='base_footprint'
            dynamic.transform.translation.x=x;dynamic.transform.translation.y=y;dynamic.transform.rotation=odom.pose.pose.orientation
            message=self.TF();message.transforms=[dynamic];self.tf.publish(message)
            static=self.Transform();static.header.stamp=stamp;static.header.frame_id='base_footprint';static.child_frame_id='laser'
            static.transform.translation.x=.1;static.transform.rotation.w=1.
            message=self.TF();message.transforms=[static];self.static.publish(message)
            scan=self.Scan();scan.header.stamp=stamp;scan.header.frame_id='laser'
            scan.angle_min=-math.pi;scan.angle_increment=2*math.pi/360;scan.angle_max=scan.angle_min+359*scan.angle_increment
            scan.scan_time=.05;scan.range_min=.05;scan.range_max=10.
            origin_x=x+.1*math.cos(yaw);origin_y=y+.1*math.sin(yaw)
            ranges=[]
            for index in range(360):
                angle=yaw+scan.angle_min+index*scan.angle_increment;dx,dy=math.cos(angle),math.sin(angle)
                choices=[]
                if abs(dx)>1e-8: choices.append(((3. if dx>0 else -3.)-origin_x)/dx)
                if abs(dy)>1e-8: choices.append(((3. if dy>0 else -3.)-origin_y)/dy)
                ranges.append(float(min(value for value in choices if value>0)))
            scan.ranges=ranges;scan.intensities=[100.]*360;self.scan.publish(scan)
            imu=self.Imu();imu.header.stamp=stamp;imu.header.frame_id='base_footprint';imu.orientation=odom.pose.pose.orientation;self.imu.publish(imu)
            joints=self.Joint();joints.header.stamp=stamp;joints.name=['wheel_7','wheel_8','wheel_9'];joints.position=[0.,0.,0.];self.joints.publish(joints)
            if self.command:self.command.publish(self.Twist())
            if self.motor:self.motor.publish(self.Bool())

    def close(self): self.stop.set();self.thread.join(timeout=3)


def record(output):
    os.environ['ROS_DOMAIN_ID']='172';os.environ['ROS_AUTOMATIC_DISCOVERY_RANGE']='LOCALHOST'
    import rclpy
    from recorder import EpisodeRecorder
    rclpy.init();node=rclpy.create_node('synthetic_room_source');room=Room(node)
    recorder=EpisodeRecorder(output/'episodes',device_profile={'demo':True,'synthetic_sensor_fixture':True},feed=NoCamera(),slam_supported=True)
    try:
        episode_id=recorder.start('synthetic','ROS SLAM room fixture',slam=True)
        for _ in range(160):
            state={'received_ns':time.monotonic_ns(),'ros_stamp_ns':node.get_clock().now().nanoseconds,
                   'values':[*room.position,0.,0.,0.]}
            recorder.sample((0.,0.,0.),(0.,0.,0.),state,False,0,True);time.sleep(.05)
        recorder.finish('synthetic','success')
        meta=json.loads((recorder.path/'episode.json').read_text())
        assert meta['complete'],meta
        assert meta['slam']['valid_for_mapping'],meta
        assert meta['slam']['counts']['/scan']>50,meta
        assert meta['slam']['counts']['/imu/data']>0,meta
        assert meta['slam']['counts']['/cmd_vel']>0,meta
        assert meta['valid_samples']==0  # No camera: not a visual policy-training sample.
        return recorder.path
    finally:
        recorder.close();room.close();node.destroy_node();rclpy.shutdown()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True)
    episode=record(args.output)
    mapping=args.output/'map'
    result=subprocess.run([sys.executable,str(ROOT/'tools/slam_map.py'),str(episode),'--output',str(mapping),'--rate','1'],capture_output=True,text=True)
    (args.output/'mapping-console.log').write_text(result.stdout+result.stderr)
    if result.returncode: raise RuntimeError(result.stdout+result.stderr)
    report=json.loads((mapping/'mapping-report.json').read_text())
    assert report['width']>20 and report['height']>20,report
    assert report['command_topics_replayed'] is False
    assert (mapping/'map.pgm').stat().st_size>400
    from PIL import Image
    Image.open(mapping/'map.pgm').save(mapping/'map.png')
    print(json.dumps({'recording':str(episode),'mapping':str(mapping),'scan_messages':report['valid_messages']['scan'],
                      'map_width':report['width'],'map_height':report['height'],'pose_graph_saved':report['pose_graph_saved'],
                      'synthetic':True,'physical_hardware_tested':False},indent=2),flush=True)


if __name__=='__main__':main()
