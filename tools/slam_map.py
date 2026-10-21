#!/usr/bin/env python3
"""Inspect a recorded episode and build a 2-D map offline with SLAM Toolbox.

Only scan/odom/TF are replayed in a separate localhost ROS domain. Never cmd_vel.
"""
import argparse
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from slam import SensorHealth, configuration, atomic_json, TYPES


def input_config(source, overrides=None):
    source = Path(source).resolve()
    if (source/'slam/config.json').is_file():
        saved = json.loads((source/'slam/config.json').read_text())
        options = {key:saved[key] for key in ('scan_topic','odom_topic','base_frame','odom_frame')}
        options['extra_topics'] = {key:value for key,value in saved['topics'].items()
                                  if key not in (saved['scan_topic'],saved['odom_topic'],'/tf','/tf_static')}
        bag = source/'slam/bag'
    else:
        options = {}; bag = source
    options.update({key:value for key,value in (overrides or {}).items() if value is not None})
    if not (bag/'metadata.yaml').is_file(): raise ValueError('완료된 ROS bag의 metadata.yaml이 없습니다')
    return bag, configuration(options)


def inspect_bag(bag, config, destination=None):
    import rosbag2_py
    from rclpy.serialization import deserialize_message, serialize_message
    from rosidl_runtime_py.utilities import get_message
    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=str(bag),storage_id=''),rosbag2_py.ConverterOptions('',''))
    types = {topic.name:topic.type for topic in reader.get_all_topics_and_types()}
    for name in (config['scan_topic'],config['odom_topic'],'/tf'):
        if types.get(name) != config['topics'][name]: raise ValueError('필수 토픽/타입 누락: '+name)
    health = SensorHealth(config); writer = None; kept = 0; dropped_map_tf = 0
    renames = {config['scan_topic']:'/scan',config['odom_topic']:'/odom','/tf':'/tf','/tf_static':'/tf_static'}
    first_time = None; last_time = None
    if destination is not None:
        writer = rosbag2_py.SequentialWriter()
        writer.open(rosbag2_py.StorageOptions(uri=str(destination),storage_id='sqlite3'),rosbag2_py.ConverterOptions('',''))
        for index,(source,target) in enumerate(renames.items()):
            writer.create_topic(rosbag2_py.TopicMetadata(id=index,name=target,type=config['topics'][source],serialization_format='cdr'))
    try:
        while reader.has_next():
            topic,data,stamp = reader.read_next()
            if topic not in config['topics']: continue
            if types.get(topic) != config['topics'][topic]: raise ValueError('기록된 토픽 타입 불일치: '+topic)
            message = deserialize_message(data,get_message(types[topic]))
            if topic not in renames:
                health.observe(topic,message)
                continue
            first_time = stamp if first_time is None else min(first_time,stamp)
            last_time = stamp if last_time is None else max(last_time,stamp)
            if topic in ('/tf','/tf_static'):
                # Existing localization map->odom must not compete with the new mapper.
                transforms = [t for t in message.transforms if t.child_frame_id != config['odom_frame']
                              and t.header.frame_id != 'map' and t.child_frame_id != 'map']
                dropped_map_tf += len(message.transforms)-len(transforms)
                message.transforms = transforms
                if not transforms:
                    health.observe(topic,message)
                    continue
                data = serialize_message(message)
            health.observe(topic,message)
            if writer: writer.write(renames[topic],data,stamp)
            kept += 1
    finally:
        if writer: writer.close()
        reader.close()
    report = health.report()
    report.update(duration_s=(last_time-first_time)/1e9 if first_time is not None else 0,
                  mapping_messages=kept, removed_map_transforms=dropped_map_tf,
                  playback_topics=['/scan','/odom','/tf','/tf_static'], command_topics_replayed=False)
    return report


def save_grid(message, output):
    """Nav2-compatible trinary PGM/YAML; ROS grid bottom row is image bottom row."""
    import yaml
    info = message.info; values = list(message.data)
    if info.width <= 0 or info.height <= 0 or len(values) != info.width*info.height:
        raise ValueError('지도 크기/데이터 불일치')
    if not math.isfinite(info.resolution) or info.resolution <= 0: raise ValueError('잘못된 지도 해상도')
    if not any(value >= 65 for value in values) or not any(0 <= value <= 19 for value in values):
        raise ValueError('장애물/빈 공간을 확인할 수 없는 지도입니다')
    if any(value < -1 or value > 100 for value in values): raise ValueError('잘못된 점유 값')
    pixels = bytearray()
    for y in range(info.height-1,-1,-1):
        for value in values[y*info.width:(y+1)*info.width]:
            pixels.append(205 if value < 0 else round((100-value)*254/100))
    output = Path(output)
    (output/'map.pgm').write_bytes(f'P5\n{info.width} {info.height}\n255\n'.encode()+pixels)
    q = info.origin.orientation; p = info.origin.position
    yaw = math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))
    (output/'map.yaml').write_text(yaml.safe_dump({'image':'map.pgm','mode':'trinary','resolution':float(info.resolution),
        'origin':[float(p.x),float(p.y),yaw],'negate':0,'occupied_thresh':.65,'free_thresh':.196},sort_keys=False))


def stop_process(process):
    if process is None or process.poll() is not None: return
    os.killpg(process.pid,signal.SIGINT)
    try: process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid,signal.SIGTERM)
        try: process.wait(timeout=2)
        except subprocess.TimeoutExpired: os.killpg(process.pid,signal.SIGKILL); process.wait(timeout=2)


def build(source, output, rate=.5, resolution=.05, domain=167, overrides=None):
    import yaml
    import rclpy
    from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy
    from nav_msgs.msg import OccupancyGrid
    from lifecycle_msgs.srv import GetState
    from ament_index_python.packages import get_package_share_directory
    if not math.isfinite(rate) or not .05 <= rate <= 2: raise ValueError('재생 속도는 0.05~2여야 합니다')
    if not math.isfinite(resolution) or not .01 <= resolution <= .2: raise ValueError('지도 해상도는 0.01~0.2m여야 합니다')
    if type(domain) is not int or not 1 <= domain <= 232 or domain == 42: raise ValueError('지도 생성은 실물 domain42와 다른 1~232 domain을 사용하세요')
    bag,config = input_config(source,overrides)
    report = inspect_bag(bag,config)
    if not report['ready']: raise ValueError('SLAM 입력 품질 검사 실패: '+json.dumps(report,ensure_ascii=False))
    output = Path(output).resolve(); output.mkdir(mode=0o700,parents=False)
    filtered = output/'mapping-bag'
    report = inspect_bag(bag,config,filtered)
    template = Path(get_package_share_directory('slam_toolbox'))/'config/mapper_params_online_sync.yaml'
    params = yaml.safe_load(template.read_text())
    params['slam_toolbox']['ros__parameters'].update(use_sim_time=True,mode='mapping',scan_topic='/scan',
        odom_frame=config['odom_frame'],base_frame=config['base_frame'],map_frame='map',resolution=resolution,
        map_update_interval=.5,minimum_time_interval=0.,minimum_travel_distance=.05,minimum_travel_heading=.1)
    params_path = output/'slam-params.yaml'; params_path.write_text(yaml.safe_dump(params))
    qos_path = output/'playback-qos.yaml'
    qos_path.write_text(yaml.safe_dump({'/tf_static':{'history':'keep_all','reliability':'reliable','durability':'transient_local'}}))
    # DDS isolation must be configured before rclpy.init and every child launch.
    os.environ['ROS_DOMAIN_ID'] = str(domain)
    os.environ['ROS_AUTOMATIC_DISCOVERY_RANGE'] = 'LOCALHOST'
    env = dict(os.environ)
    rclpy.init(); node = rclpy.create_node('lekiwi_offline_map_monitor')
    latest = []
    def receive(message):
        if message.info.width and any(value >= 65 for value in message.data): latest[:] = [message]
    subscription = node.create_subscription(OccupancyGrid,'/map',receive,
        QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL,reliability=ReliabilityPolicy.RELIABLE))
    mapper = None; player = None
    try:
        with (output/'mapper.log').open('w') as log, (output/'playback.log').open('w') as play_log:
            mapper = subprocess.Popen(['ros2','launch','slam_toolbox','online_sync_launch.py',
                'slam_params_file:='+str(params_path),'use_sim_time:=true'],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            client = node.create_client(GetState,'/slam_toolbox/get_state')
            deadline = time.monotonic()+40
            while time.monotonic() < deadline:
                if mapper.poll() is not None: raise ValueError('SLAM Toolbox 시작 실패: mapper.log 확인')
                if client.wait_for_service(timeout_sec=.2):
                    future = client.call_async(GetState.Request())
                    rclpy.spin_until_future_complete(node,future,timeout_sec=1)
                    if future.done() and future.result() and future.result().current_state.id == 3: break
            else: raise ValueError('SLAM Toolbox 활성화 시간 초과')
            player = subprocess.Popen(['ros2','bag','play',str(filtered),'--clock','100','--rate',str(rate),
                '--qos-profile-overrides-path',str(qos_path)],env=env,stdout=play_log,stderr=subprocess.STDOUT,start_new_session=True)
            deadline = time.monotonic()+report['duration_s']/rate+60
            while player.poll() is None:
                rclpy.spin_once(node,timeout_sec=.1)
                if mapper.poll() is not None or time.monotonic()>deadline: raise ValueError('지도 생성 실패/시간 초과: 로그 확인')
            if player.returncode: raise ValueError('ROS bag 재생 실패: playback.log 확인')
            # The map timer can still be processing the last batch after playback.
            deadline = time.monotonic()+5
            while time.monotonic() < deadline: rclpy.spin_once(node,timeout_sec=.1)
            if not latest: raise ValueError('생성된 지도가 없습니다. 센서 TF/타임스탬프와 mapper.log를 확인하세요')
            save_grid(latest[0],output)
            episode_meta = Path(source)/'episode.json'
            synthetic = json.loads(episode_meta.read_text()).get('device_profile',{}).get('demo') if episode_meta.is_file() else None
            report.update(map_frame=latest[0].header.frame_id,map_stamp_ns=latest[0].header.stamp.sec*10**9+latest[0].header.stamp.nanosec,
                          width=latest[0].info.width,height=latest[0].info.height,source=str(bag),
                          config=config,map_file='map.yaml',synthetic_source=synthetic,physical_navigation_tested=False)
            from slam_toolbox.srv import SerializePoseGraph
            graph_client = node.create_client(SerializePoseGraph,'/slam_toolbox/serialize_map')
            report['pose_graph_saved'] = False
            if graph_client.wait_for_service(timeout_sec=2):
                request = SerializePoseGraph.Request(); request.filename = str(output/'map')
                future = graph_client.call_async(request)
                rclpy.spin_until_future_complete(node,future,timeout_sec=15)
                report['pose_graph_saved'] = bool(future.done() and future.result() and future.result().result == 0 and (output/'map.posegraph').exists())
            atomic_json(output/'mapping-report.json',report)
    finally:
        stop_process(player); stop_process(mapper)
        node.destroy_node(); rclpy.shutdown()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recording',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--inspect-only',action='store_true')
    parser.add_argument('--rate',type=float,default=.5)
    parser.add_argument('--resolution',type=float,default=.05)
    parser.add_argument('--domain-id',type=int,default=167)
    for key in ('scan-topic','odom-topic','base-frame','odom-frame'): parser.add_argument('--'+key)
    args = parser.parse_args()
    overrides = {key:getattr(args,key) for key in ('scan_topic','odom_topic','base_frame','odom_frame')}
    if not args.inspect_only and args.output is None: parser.error('--output의 새 출력 경로가 필요합니다')
    try:
        if args.inspect_only:
            bag,config = input_config(args.recording,overrides); report = inspect_bag(bag,config)
        else: report = build(args.recording,args.output,args.rate,args.resolution,args.domain_id,overrides)
        print(json.dumps(report,ensure_ascii=False,indent=2))
        return 0 if report['ready'] else 1
    except (OSError,ValueError,ImportError) as error:
        print('지도 생성 실패: '+str(error),file=sys.stderr); return 1


if __name__ == '__main__': raise SystemExit(main())
