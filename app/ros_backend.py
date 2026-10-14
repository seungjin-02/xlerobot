"""ROS 2 adapter. Only the base controller owns serial/motor access."""
import os
import subprocess
import time
from pathlib import Path

class RosBackend:
    def __init__(self, profile, workspace=None):
        import rclpy
        from geometry_msgs.msg import Twist
        from nav_msgs.msg import Odometry
        from std_msgs.msg import Bool
        from std_srvs.srv import SetBool
        from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy
        self.rclpy, self.Twist, self.SetBool = rclpy, Twist, SetBool
        rclpy.init()
        self.node = rclpy.create_node('lekiwi_phone_control')
        self.pub = self.node.create_publisher(Twist, '/cmd_vel', 1)
        self.client = self.node.create_client(SetBool, '/motor_power')
        self.ready = None
        self.odom_time = 0
        self.latest_state = None
        self.others = 0
        self.graph_time = 0
        self.profile = Path(profile)
        self.workspace = Path(workspace) if workspace else Path.home() / 'lekiwi_autonomy_ws'
        import yaml
        self.output_parameters = yaml.safe_load(self.profile.read_text())['lekiwi_node']['ros__parameters']
        (Path.home() / '.local/state/lekiwi-phone').mkdir(parents=True, exist_ok=True)
        from rclpy.parameter_client import AsyncParameterClient
        self.params = AsyncParameterClient(self.node, '/lekiwi_node')
        self.param_future = None
        self.linear_limit, self.angular_limit = .03, .1
        self.param_time = 0
        self.process = None
        self.base_log = None
        self.sub_ready = self.node.create_subscription(Bool, '/motor_ready', self._ready, QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL, reliability=ReliabilityPolicy.RELIABLE))
        self.sub_odom = self.node.create_subscription(Odometry, '/odom', self._odom, 1)

    def _ready(self, msg): self.ready = bool(msg.data)
    def _odom(self, msg):
        import math
        self.odom_time = time.monotonic()
        p, q, v = msg.pose.pose.position, msg.pose.pose.orientation, msg.twist.twist
        yaw = math.atan2(2 * (q.w*q.z + q.x*q.y), 1 - 2 * (q.y*q.y + q.z*q.z))
        self.latest_state = {'received_ns': time.monotonic_ns(), 'ros_stamp_ns': msg.header.stamp.sec * 1000000000 + msg.header.stamp.nanosec,
                             'values': [p.x, p.y, yaw, v.linear.x, v.linear.y, v.angular.z]}

    def observation(self):
        return self.latest_state


    def poll(self):
        self.rclpy.spin_once(self.node, timeout_sec=0)
        now = time.monotonic()
        if now - self.graph_time > .2:
            self.others = sum(1 for info in self.node.get_publishers_info_by_topic('/cmd_vel') if info.node_name != self.node.get_name())
            self.graph_time = now
        if self.param_future is not None and self.param_future.done():
            result = self.param_future.result()
            if result is not None:
                values = [(p.double_value if p.type == 3 else float(p.integer_value)) for p in result.values]
                if len(values) == 7 and all(v > 0 for v in values):
                    linear, angular, wheel, radius, base, scale, ticks = values
                    envelope = min(wheel, ticks / scale)
                    self.output_parameters.update(max_wheel_speed=wheel, wheel_radius=radius, base_radius=base, speed_tick_scale=scale, speed_tick_limit=ticks)
                    self.linear_limit = min(.9, linear)
                    self.angular_limit = min(4.5, angular)
            self.param_future = None
        if now - self.param_time > 2 and self.param_future is None and self.params.services_are_ready():
            self.param_future = self.params.get_parameters(['max_linear_speed', 'max_angular_z', 'max_wheel_speed', 'wheel_radius', 'base_radius', 'speed_tick_scale', 'speed_tick_limit'])
            self.param_time = now

    def status(self):
        available = self.client.service_is_ready() and time.monotonic() - self.odom_time < .75
        return {'available': available,
                'motor_ready': self.ready, 'other_publishers': self.others, 'demo': False,
                'max_linear': self.linear_limit if available else min(.9, self.output_parameters['max_linear_speed']), 'max_angular': self.angular_limit if available else min(4.5, self.output_parameters['max_angular_z']),
                'wheel_output_limit_note': '바퀴 출력 상한을 유지합니다. 명령값과 실제 주행 속도는 다를 수 있습니다.',
                'base_running': self.process is not None and self.process.poll() is None}

    def _power(self, enabled):
        if not self.client.wait_for_service(timeout_sec=1):
            raise RuntimeError('바퀴 제어 서비스가 없습니다')
        request = self.SetBool.Request(); request.data = enabled
        future = self.client.call_async(request)
        deadline = time.monotonic() + 2
        while not future.done() and time.monotonic() < deadline:
            self.rclpy.spin_once(self.node, timeout_sec=.02)
        if not future.done() or future.result() is None or not future.result().success:
            raise RuntimeError('모터 전원 변경 확인 실패')
        deadline = time.monotonic() + .5
        while self.ready is not enabled and time.monotonic() < deadline:
            self.rclpy.spin_once(self.node, timeout_sec=.02)
        if self.ready is not enabled:
            raise RuntimeError('모터 준비 상태 확인 실패')

    def _ensure_base(self):
        if self.status()['available']:
            expected=str(self.workspace/'install/lekiwi_node/lib/lekiwi_node/lekiwi_node')
            allowed={str(self.profile),str(self.workspace/'base-profile-initial.yaml')}
            matched=False
            for entry in Path('/proc').iterdir():
                if not entry.name.isdigit():continue
                try:
                    cmd=[a.decode(errors='replace') for a in (entry/'cmdline').read_bytes().split(b'\0') if a]
                    if cmd and cmd[0]==expected and entry.stat().st_uid==os.getuid() and '--params-file' in cmd:
                        params_file=cmd[cmd.index('--params-file')+1]
                        if params_file in allowed:
                            import yaml
                            params=yaml.safe_load(Path(params_file).read_text())['lekiwi_node']['ros__parameters']
                            if len(params.get('wheel_ids',[]))==3 and set(params['wheel_ids'])=={7,8,9} and params.get('motor_backend')=='feetech' and params.get('enable_motor_write') is True:
                                self.output_parameters.update(params)
                                self.linear_limit=min(.9,params['max_linear_speed']);self.angular_limit=min(4.5,params['max_angular_z'])
                                matched=True
                except (OSError,ValueError,IndexError,KeyError):continue
            if not matched:raise RuntimeError('알 수 없는 기존 바퀴 제어가 실행 중입니다. 해당 제어를 먼저 종료하세요.')
            return
        # Do not start a duplicate driver when another program owns hardware.
        import yaml
        config = yaml.safe_load(self.profile.read_text())['lekiwi_node']['ros__parameters']
        serial = config['serial_port']
        if not Path(serial).exists() or config.get('torque_enable') is not False:
            raise RuntimeError('기기 프로필/시리얼 연결을 확인하세요')
        if config.get('speed_tick_limit', 32767) > 3000 or config.get('max_wheel_speed', 100) * config.get('speed_tick_scale', 1) > 32767:
            raise RuntimeError('바퀴 속도 범위가 3000 ticks/s를 초과합니다')
        if len(config.get('wheel_ids', [])) != 3 or set(config.get('wheel_ids', [])) != {7, 8, 9}:
            raise RuntimeError('바퀴 전용 ID 7·8·9 프로필이 필요합니다')
        if config.get('max_linear_speed', 1) > .9 or config.get('max_angular_z', 5) > 4.5 or config.get('cmd_vel_timeout', 1) > .3:
            raise RuntimeError('기기 프로필의 속도/정지 상한이 맞지 않습니다')
        for entry in Path('/proc').iterdir():
            if not entry.name.isdigit(): continue
            try: cmd = (entry / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace')
            except (OSError, PermissionError): continue
            if '/lekiwi_node/lekiwi_node' in cmd or '-m lerobot.robots.lekiwi.lekiwi_host' in cmd:
                raise RuntimeError('기존 바퀴 제어가 실행 중이지만 응답하지 않습니다. 기존 작업 상태를 확인하세요.')
        if self.process and self.process.poll() is None:
            raise RuntimeError('바퀴 제어 시작을 기다리는 중입니다')
        self.base_log = open(Path.home() / '.local/state/lekiwi-phone/base.log', 'a')
        self.process = subprocess.Popen(['ros2', 'run', 'lekiwi_node', 'lekiwi_node', '--ros-args', '--params-file', str(self.profile)], stdout=self.base_log, stderr=subprocess.STDOUT, start_new_session=True)
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            self.poll()
            if self.status()['available']: return
            if self.process.poll() is not None: break
            time.sleep(.02)
        raise RuntimeError('바퀴 제어 시작 실패: base.log를 확인하세요')

    def prepare_fast(self):
        """User-selected handover, only while the wheels are disarmed."""
        self.poll()
        if self.ready is True or self.others:
            raise RuntimeError('기존 조종을 종료하고 모터가 꺼진 상태에서 전환하세요')
        import signal
        expected = str(self.workspace / 'install/lekiwi_node/lib/lekiwi_node/lekiwi_node')
        permitted_profile = str(self.workspace / 'base-profile-initial.yaml')
        candidates = []
        for entry in Path('/proc').iterdir():
            if not entry.name.isdigit(): continue
            try:
                args = (entry / 'cmdline').read_bytes().split(b'\0')
                cmd = [a.decode(errors='replace') for a in args if a]
                if cmd and cmd[0] == expected:
                    if entry.stat().st_uid != os.getuid() or ('--params-file' not in cmd):
                        raise RuntimeError('알 수 없는 바퀴 제어는 자동 전환하지 않습니다')
                    profile = cmd[cmd.index('--params-file') + 1]
                    if profile not in (permitted_profile, str(self.profile)):
                        raise RuntimeError('다른 기기 프로필이 실행 중입니다')
                    candidates.append(int(entry.name))
            except (FileNotFoundError, PermissionError): continue
        if len(candidates) > 1:
            raise RuntimeError('여러 바퀴 제어가 실행 중입니다')
        for pid in candidates:
            # Existing node is disarmed; SIGINT lets it perform its own cleanup.
            os.kill(pid, signal.SIGINT)
            deadline = time.monotonic() + 4
            while Path(f'/proc/{pid}').exists() and time.monotonic() < deadline:
                self.poll(); time.sleep(.03)
            if Path(f'/proc/{pid}').exists():
                raise RuntimeError('기존 제어가 종료되지 않았습니다')
        self.ready = None; self.odom_time = 0
        self.linear_limit, self.angular_limit = .03, .1
        if self.param_future is not None:
            self.param_future.cancel(); self.param_future = None
        self.param_time = 0
        self._ensure_base()
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            self.poll()
            if self.linear_limit >= .89 and self.ready is False:
                return
            time.sleep(.02)
        raise RuntimeError('고속 프로필 적용 확인 실패')

    def arm(self):
        self._ensure_base()
        self.poll()
        if self.ready or self.others:
            raise RuntimeError('다른 조종을 종료한 뒤 다시 시도하세요')
        self.publish((0., 0., 0.))
        try:
            self._power(True)
        except Exception:
            self.publish((0., 0., 0.))
            try: self._power(False)
            except Exception: pass
            raise

    def disarm(self):
        self.publish((0., 0., 0.))
        self._power(False)

    def limit_motion(self, motion):
        from speed_limiter import limit_motion
        return limit_motion(motion, self.output_parameters)

    def publish(self, motion):
        motion = self.limit_motion(motion)
        message = self.Twist()
        message.linear.x, message.linear.y, message.angular.z = motion
        self.pub.publish(message)
        return motion

    def close(self):
        if self.process and self.process.poll() is None:
            import signal
            os.killpg(self.process.pid, signal.SIGINT)
            try: self.process.wait(timeout=3)
            except subprocess.TimeoutExpired: os.killpg(self.process.pid, signal.SIGTERM)
        if self.base_log: self.base_log.close()
        self.node.destroy_node()
        self.rclpy.shutdown()
