"""SLAM recording configuration, sensor quality and isolated recorder lifecycle.

No ROS imports here: diagnostics and the normal camera recorder work without ROS.
"""
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

TYPES = {
    'scan': 'sensor_msgs/msg/LaserScan', 'odom': 'nav_msgs/msg/Odometry',
    'tf': 'tf2_msgs/msg/TFMessage', 'tf_static': 'tf2_msgs/msg/TFMessage',
}
EXTRAS = {'/imu/data': 'sensor_msgs/msg/Imu', '/joint_states': 'sensor_msgs/msg/JointState',
          '/points': 'sensor_msgs/msg/PointCloud2', '/cmd_vel': 'geometry_msgs/msg/Twist',
          '/motor_ready': 'std_msgs/msg/Bool', '/diagnostics': 'diagnostic_msgs/msg/DiagnosticArray',
          '/battery_state':'sensor_msgs/msg/BatteryState','/camera/camera_info':'sensor_msgs/msg/CameraInfo',
          '/amcl_pose':'geometry_msgs/msg/PoseWithCovarianceStamped','/plan':'nav_msgs/msg/Path',
          '/local_plan':'nav_msgs/msg/Path','/goal_pose':'geometry_msgs/msg/PoseStamped','/map':'nav_msgs/msg/OccupancyGrid'}
ALLOWED_TYPES = set(TYPES.values()) | set(EXTRAS.values()) | {'geometry_msgs/msg/TwistStamped'}


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2))
    temporary.chmod(0o600); temporary.replace(path)


def configuration(options=None, profile=None):
    options, profile = options or {}, profile or {}
    if not isinstance(options, dict): raise ValueError('slam 설정은 객체여야 합니다')
    result = {'scan_topic': options.get('scan_topic', '/scan'),
              'odom_topic': options.get('odom_topic', '/odom'),
              'base_frame': options.get('base_frame', profile.get('base_frame', 'base_footprint')),
              'odom_frame': options.get('odom_frame', profile.get('odom_frame', 'odom'))}
    for key, value in result.items():
        pattern = r'/[A-Za-z_][A-Za-z0-9_]*(?:/[A-Za-z_][A-Za-z0-9_]*)*' if key.endswith('topic') else r'[A-Za-z_][A-Za-z0-9_]*(?:/[A-Za-z_][A-Za-z0-9_]*)*'
        if not isinstance(value, str) or not re.fullmatch(pattern, value): raise ValueError(key+' 이름이 잘못됐습니다')
    if result['base_frame'] == result['odom_frame']: raise ValueError('base와 odom 프레임은 달라야 합니다')
    topics = {result['scan_topic']: TYPES['scan'], result['odom_topic']: TYPES['odom'],
              '/tf': TYPES['tf'], '/tf_static': TYPES['tf_static']}
    if len(topics) != 4: raise ValueError('scan/odom/TF 토픽 이름은 서로 달라야 합니다')
    extras = options.get('extra_topics', EXTRAS)
    if not isinstance(extras, dict) or len(extras) > 24: raise ValueError('추가 토픽 설정이 잘못됐습니다')
    for name, kind in extras.items():
        if (not isinstance(name, str) or not re.fullmatch(r'/[A-Za-z_][A-Za-z0-9_]*(?:/[A-Za-z_][A-Za-z0-9_]*)*', name)
                or kind not in ALLOWED_TYPES or name in topics):
            raise ValueError('지원하지 않거나 중복된 추가 센서 토픽입니다')
        topics[name] = kind
    result['topics'] = topics
    return result


def available(demo=False):
    if demo: return False
    return all(importlib.util.find_spec(name) is not None for name in ('rclpy', 'rosbag2_py'))


def stamp_ns(stamp):
    return int(stamp.sec)*1_000_000_000 + int(stamp.nanosec)


class SensorHealth:
    def __init__(self, config):
        self.config = config
        self.counts = {name: 0 for name in config['topics']}
        self.valid = {'scan': 0, 'odom': 0}
        self.last_received = {}; self.last_stamp = {}; self.edges = {}
        self.scan_frame = None; self.invalid = 0; self.clock_regressions = 0

    def observe(self, topic, message, received=None):
        now = time.monotonic() if received is None else received
        self.counts[topic] += 1
        if topic in ('/tf', '/tf_static'):
            for transform in message.transforms:
                parent, child = transform.header.frame_id, transform.child_frame_id
                q = transform.transform.rotation; t = transform.transform.translation
                values = (q.x,q.y,q.z,q.w,t.x,t.y,t.z)
                if (not parent or not child or parent == child or not all(math.isfinite(v) for v in values)
                        or abs(sum(v*v for v in (q.x,q.y,q.z,q.w))-1) > .05
                        or (topic != '/tf_static' and stamp_ns(transform.header.stamp) <= 0)):
                    self.invalid += 1; continue
                self.edges[(parent,child)] = (topic == '/tf_static',now,stamp_ns(transform.header.stamp))
            return
        role = 'scan' if topic == self.config['scan_topic'] else 'odom' if topic == self.config['odom_topic'] else None
        if role is None: return
        stamp = stamp_ns(message.header.stamp)
        if stamp <= 0 or not message.header.frame_id:
            self.invalid += 1; return
        if stamp < self.last_stamp.get(role,0): self.clock_regressions += 1
        self.last_stamp[role] = stamp
        if role == 'scan':
            finite = [value for value in message.ranges if math.isfinite(value) and message.range_min <= value <= message.range_max]
            if (not finite or len(message.ranges) < 2 or not math.isfinite(message.angle_increment)
                    or message.angle_increment <= 0 or not math.isfinite(message.range_max)
                    or message.range_max <= message.range_min
                    or not all(math.isfinite(v) for v in (message.angle_min,message.angle_max,message.scan_time,message.time_increment))
                    or message.scan_time < 0 or message.time_increment < 0):
                self.invalid += 1; return
            self.scan_frame = message.header.frame_id
        else:
            if (message.header.frame_id != self.config['odom_frame'] or message.child_frame_id != self.config['base_frame']):
                self.invalid += 1; return
            p,q = message.pose.pose.position,message.pose.pose.orientation
            v,w = message.twist.twist.linear,message.twist.twist.angular
            values = (p.x,p.y,p.z,q.x,q.y,q.z,q.w,v.x,v.y,v.z,w.x,w.y,w.z)
            if not all(math.isfinite(value) for value in values) or abs(q.x*q.x+q.y*q.y+q.z*q.z+q.w*q.w-1) > .05:
                self.invalid += 1; return
        self.valid[role] += 1; self.last_received[role] = now

    def connected(self, source, target, now=None):
        if not source or not target: return False
        graph = {}
        for (parent,child),(static,received,stamp) in self.edges.items():
            if now is not None and not static and now-received > 2: continue
            reference = self.last_stamp.get('scan')
            if reference and not static and abs(reference-stamp)>2_000_000_000: continue
            graph.setdefault(parent,set()).add(child)
            graph.setdefault(child,set()).add(parent)
        seen = {source}; queue = [source]
        for frame in queue:
            for neighbor in graph.get(frame,()):
                if neighbor not in seen: seen.add(neighbor); queue.append(neighbor)
        return target in seen

    def report(self, now=None):
        missing = []
        for role in ('scan','odom'):
            if not self.valid[role] or (now is not None and now-self.last_received.get(role,0) > 2): missing.append(role)
        if self.valid['scan'] and self.valid['odom'] and abs(self.last_stamp['scan']-self.last_stamp['odom'])>1_000_000_000:
            missing.append('scan/odom 시각 차이 1초 초과')
        for source,target in ((self.config['odom_frame'],self.config['base_frame']),
                              (self.config['base_frame'],self.scan_frame)):
            if not self.connected(source,target,now): missing.append('TF: '+source+' → '+str(target or 'laser'))
        return {'ready':not missing and self.invalid == 0 and self.clock_regressions == 0,
                'missing':missing, 'counts':dict(self.counts), 'valid_messages':dict(self.valid),
                'scan_frame':self.scan_frame, 'invalid_messages':self.invalid,
                'clock_regressions':self.clock_regressions,
                'last_header_stamp_ns':dict(self.last_stamp),
                'tf_edges':[{'parent':p,'child':c,'static':value[0],'stamp_ns':value[2]} for (p,c),value in sorted(self.edges.items())]}


class SlamSession:
    def __init__(self, config):
        self.config = config; self.process = None; self.folder = None; self.log = None
        self.stopping = False; self.failure = None

    def start(self, episode):
        self.folder = Path(episode)/'slam'; self.folder.mkdir(mode=0o700)
        atomic_json(self.folder/'config.json',self.config)
        self.log = (self.folder/'capture.log').open('w')
        self.process = subprocess.Popen([sys.executable,str(Path(__file__).with_name('slam_capture.py')),
            '--directory',str(self.folder)], stdin=subprocess.DEVNULL,stdout=self.log,stderr=subprocess.STDOUT,
            start_new_session=True)
        deadline = time.monotonic()+8
        while time.monotonic() < deadline:
            status = self.status()
            if self.process.poll() is not None: break
            if status.get('ready'): return
            time.sleep(.05)
        status = self.stop()
        raise ValueError('SLAM 기록 준비 실패: '+str(status.get('error') or ', '.join(status.get('missing',[])) or 'capture.log 확인'))

    def status(self):
        try: status = json.loads((self.folder/'status.json').read_text())
        except (OSError,ValueError,TypeError): status = {'ready':False,'missing':['센서 수신 대기']}
        if self.process is not None and self.process.poll() is not None and not self.stopping:
            self.failure = status.get('error') or 'ROS bag 기록 프로세스가 예기치 않게 종료됐습니다'
        if self.failure:
            status = {**status,'ready':False,'error':self.failure}
        return status

    def stop(self):
        self.status()  # Detect a worker which exited before stop was requested.
        self.stopping = True
        if self.process is not None and self.process.poll() is None:
            self.process.send_signal(signal.SIGINT)
            try: self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try: self.process.wait(timeout=1)
                except subprocess.TimeoutExpired: self.process.kill(); self.process.wait(timeout=1)
        if self.log: self.log.close(); self.log = None
        status = self.status()
        return {**status, 'complete':bool(status.get('bag_closed') and not status.get('error') and
                                          self.process is not None and self.process.returncode == 0)}
