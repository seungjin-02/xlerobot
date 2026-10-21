#!/usr/bin/env python3
"""Separate ROS process: raw CDR sensor messages, no motor writes or publishers."""
import argparse
import json
from pathlib import Path
import shutil
import signal
import time

from slam import SensorHealth, atomic_json


def capture(directory):
    import rclpy
    from rclpy.signals import SignalHandlerOptions
    from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
    from rclpy.serialization import serialize_message
    from rosidl_runtime_py.utilities import get_message
    import rosbag2_py
    folder = Path(directory)
    config = json.loads((folder/'config.json').read_text())
    health = SensorHealth(config)
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    node = rclpy.create_node('lekiwi_slam_recorder')
    def clock_sample():
        return {'ros_ns':node.get_clock().now().nanoseconds,'monotonic_ns':time.monotonic_ns(),
                'wall_ns':time.time_ns(),'use_sim_time':bool(node.get_parameter('use_sim_time').value)}
    clock_start = clock_sample()
    writer = rosbag2_py.SequentialWriter()
    writer.open(rosbag2_py.StorageOptions(uri=str(folder/'bag'),storage_id='sqlite3'),
                rosbag2_py.ConverterOptions('',''))
    stopping = False; error = None; subscriptions = []
    def stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGINT,stop); signal.signal(signal.SIGTERM,stop)
    def receive(topic, message):
        writer.write(topic,serialize_message(message),node.get_clock().now().nanoseconds)
        health.observe(topic,message)
    for index,(topic,kind) in enumerate(config['topics'].items()):
        static = topic == '/tf_static' or kind == 'nav_msgs/msg/OccupancyGrid'
        qos = QoSProfile(depth=100, reliability=ReliabilityPolicy.RELIABLE if static else ReliabilityPolicy.BEST_EFFORT,
                         durability=DurabilityPolicy.TRANSIENT_LOCAL if static else DurabilityPolicy.VOLATILE)
        writer.create_topic(rosbag2_py.TopicMetadata(id=index,name=topic,type=kind,serialization_format='cdr'))
        subscriptions.append(node.create_subscription(get_message(kind),topic,
            lambda message, name=topic: receive(name,message),qos))
    last_report = 0
    try:
        while not stopping:
            rclpy.spin_once(node,timeout_sec=.05)
            now = time.monotonic()
            if now-last_report > .5:
                if shutil.disk_usage(folder).free < 256*1024**2: raise OSError('SLAM 저장 공간 256 MiB 미만')
                for topic in (config['scan_topic'],config['odom_topic']):
                    if len(node.get_publishers_info_by_topic(topic)) > 1:
                        raise ValueError('중복 센서 발행자: '+topic)
                status = health.report(now)
                status.update(bag_closed=False,error=None,clock_start=clock_start,clock_latest=clock_sample())
                atomic_json(folder/'status.json',status)
                last_report = now
    except Exception as exception:
        error = str(exception)
    finally:
        writer.close()
        status = health.report(time.monotonic())
        status.update(bag_closed=True,error=error,clock_start=clock_start,clock_latest=clock_sample())
        atomic_json(folder/'status.json',status)
        node.destroy_node(); rclpy.shutdown()
    return 1 if error else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',required=True,type=Path)
    args = parser.parse_args()
    try: raise SystemExit(capture(args.directory))
    except Exception as error:
        atomic_json(args.directory/'status.json',{'ready':False,'bag_closed':False,'error':str(error)})
        raise
