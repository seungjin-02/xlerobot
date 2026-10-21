#!/usr/bin/env python3
"""Read-only live SLAM input check. No motor publishers or service calls."""
import argparse
import json
import math
import os
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from slam import configuration,SensorHealth


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=Path.home()/'.config/lekiwi-phone/config.json')
    parser.add_argument('--seconds',type=float,default=5.)
    args=parser.parse_args()
    if not math.isfinite(args.seconds) or not 1<=args.seconds<=60:parser.error('--seconds는 1~60이어야 합니다')
    try:
        import yaml
        import rclpy
        from rosidl_runtime_py.utilities import get_message
        from rclpy.qos import QoSProfile,ReliabilityPolicy,DurabilityPolicy
        robot=json.loads(args.config.read_text())
        wheel=yaml.safe_load(Path(robot['profile']).read_text())['lekiwi_node']['ros__parameters']
        config=configuration(robot.get('slam'),wheel);health=SensorHealth(config)
        os.environ.setdefault('ROS_DOMAIN_ID','42');os.environ.setdefault('ROS_AUTOMATIC_DISCOVERY_RANGE','LOCALHOST')
        rclpy.init();node=rclpy.create_node('lekiwi_slam_input_check');subscriptions=[]
        try:
            for topic,kind in config['topics'].items():
                static=topic=='/tf_static' or kind=='nav_msgs/msg/OccupancyGrid'
                qos=QoSProfile(depth=100,reliability=ReliabilityPolicy.RELIABLE if static else ReliabilityPolicy.BEST_EFFORT,
                    durability=DurabilityPolicy.TRANSIENT_LOCAL if static else DurabilityPolicy.VOLATILE)
                subscriptions.append(node.create_subscription(get_message(kind),topic,lambda m,t=topic:health.observe(t,m),qos))
            deadline=time.monotonic()+args.seconds
            while time.monotonic()<deadline:rclpy.spin_once(node,timeout_sec=.05)
            report=health.report(time.monotonic())
            report['publishers']={topic:len(node.get_publishers_info_by_topic(topic)) for topic in config['topics']}
            if any(report['publishers'][topic]>1 for topic in (config['scan_topic'],config['odom_topic'])):
                report['ready']=False;report['missing'].append('중복 scan/odom 발행자')
            print(json.dumps(report,ensure_ascii=False,indent=2))
            return 0 if report['ready'] else 1
        finally:node.destroy_node();rclpy.shutdown()
    except (OSError,ValueError,ImportError,KeyError) as error:
        print('센서 확인 실패: '+str(error),file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
