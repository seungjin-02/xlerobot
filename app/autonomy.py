"""Web-owned SLAM/patrol session with exclusive base access and episode recording.

The default configuration cannot start motion: measured calibration is mandatory.
Planning runs outside the motor loop. Nav2 output passes through NavigationGuard.
"""
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import threading
import time

from core import ControlError,DemoBackend
from navigation_guard import NavigationGuard
from patrol import Grid,Limits,Mission,finite
from slam import SensorHealth,configuration

ROOT=Path(__file__).resolve().parents[1]


def calibration(config):
    value=config.get('patrol',{}).get('calibration',{})
    bounded=(value.get('geometry_mode')=='confirmed_conservative_envelope'
             and value.get('envelope_confirmed') is True
             and value.get('stationary_sensor_test_passed') is True
             and value.get('lidar_pose_source')=='installed_urdf_stationary_verified')
    if value.get('measured') is not True and not bounded:
        raise ValueError('LiDAR 위치·방향과 바퀴·케이블 포함 외곽 크기 실측 설정이 필요합니다')
    radius=value.get('robot_radius')
    if not finite(radius) or not .05<=radius<=2:raise ValueError('실측 외접 반경이 필요합니다')
    transform=value.get('lidar_transform',{})
    if not all(finite(transform.get(k)) for k in ('x','y','z','roll','pitch','yaw')):
        raise ValueError('LiDAR 실측 좌표 6개가 필요합니다')
    if any(abs(transform[k])>2 for k in ('x','y','z')) or any(abs(transform[k])>2*math.pi for k in ('roll','pitch','yaw')):
        raise ValueError('LiDAR 실측 좌표 범위를 확인하세요')
    import re
    result={k:value.get(k) for k in ('robot_radius','lidar_transform','external_lidar_tf','geometry_mode','lidar_pose_source')}
    for k,default in [('base_frame','base_footprint'),('lidar_frame','lidar_link')]:
        result[k]=value.get(k,default)
        if not isinstance(result[k],str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_/]*',result[k]):
            raise ValueError('잘못된 센서 프레임')
    if result['base_frame']==result['lidar_frame']:raise ValueError('센서와 본체 프레임이 같을 수 없습니다')
    if result['external_lidar_tf'] not in (None,False,True):raise ValueError('external_lidar_tf는 boolean입니다')
    return result


class Autonomy:
    def __init__(self,app,config):
        self.app,self.config=app,config
        self.backend=app.control.backend
        self.owner=None;self.thread=None;self.phase='idle';self.error=None;self.mission=None
        self.grid=None;self.pose=None;self.last_report=None;self.guard=None;self.process=None
        self.stop_event=threading.Event();self.paused=False;self.results=queue.SimpleQueue()
        self.last_planner=0.;self.outcome='unfinished';self.subscriptions=[];self.health=None
        self.health_lock=threading.Lock();self.run_dir=None;self.pending_action=None;self.handle=None
        self.episode=None;self.calibration_error=None
        self.recording_expected=False;self.return_requested=False
        self.filtered_publisher=None;self.navigation_scan_topic=None
        self.speed_multiplier=3
        try:calibration(config)
        except ValueError as e:self.calibration_error=str(e)

    @property
    def busy(self):return self.thread is not None and self.thread.is_alive()

    def status(self,owner=None):
        with self.health_lock:
            sensor_health=self.health.report(time.monotonic()) if self.health else None
        return {'phase':self.phase,'busy':self.busy,'mine':self.busy and owner==self.owner,
                'configured':self.calibration_error is None and not isinstance(self.backend,DemoBackend),
                'blocked_reason':'실물 ROS 센서가 없는 데모에서는 자율주행을 시작하지 않습니다' if isinstance(self.backend,DemoBackend) else self.calibration_error,
                'error':self.error,'fault_sensor_health':getattr(self,'fault_sensor_health',None),'recording_episode':self.episode,'mission':self.last_report,
                'limits':getattr(self,'public_limits',None),'paused':self.paused,
                'recording_required':False,'local_only':True,'sensor_health':sensor_health,'speed_multiplier':self.speed_multiplier}

    def map_view(self):
        grid=self.grid
        if grid is None:return {'available':False,'pose':self.pose}
        stride=max(1,math.ceil(math.sqrt(len(grid.data)/40000)))
        values=[];width=math.ceil(grid.width/stride);height=math.ceil(grid.height/stride)
        for row in range(height):
            for col in range(width):
                block=[grid.data[y*grid.width+x] for y in range(row*stride,min(grid.height,(row+1)*stride))
                       for x in range(col*stride,min(grid.width,(col+1)*stride))]
                values.append(100 if any(v>20 for v in block) else -1 if any(v==-1 for v in block) else 0)
        mission=self.mission;goal=mission.active if mission else None
        return {'available':True,'width':width,'height':height,'resolution':grid.resolution*stride,
                'origin':[grid.origin_x,grid.origin_y,grid.origin_yaw],'data':values,'pose':self.pose,
                'trail':mission.trail[-2000:] if mission else [],'goal':[goal.x,goal.y] if goal else None,
                'map_age_s':max(0,time.monotonic()-grid.received_at),'display_downsampled':stride>1}

    def start(self,owner,data):
        with self.app.control.lock:
            if self.busy or self.app.control.owner or self.app.recorder.active or self.app.recorder.finishing:
                raise ControlError('기존 조종·기록·자율주행을 먼저 종료하세요')
            if isinstance(self.backend,DemoBackend):raise ValueError('데모에서 실물 자율주행은 시작하지 않습니다')
            measured=calibration(self.config)
            mode=data.get('mode','patrol')
            if mode not in ('patrol','round_trip'):raise ValueError('알 수 없는 운행 방식')
            round_trip_distance=data.get('target_distance',1.) if mode=='round_trip' else None
            # Validate the mission before changing controller/session state.
            if mode=='round_trip' and (isinstance(round_trip_distance,bool) or not finite(round_trip_distance) or not .1<=round_trip_distance<=1.):
                raise ValueError('왕복 목표 거리는 0.1~1m여야 합니다')
            max_distance=data.get('max_distance',50.)
            if mode=='round_trip':
                if not finite(max_distance) or isinstance(max_distance,bool):raise ValueError('잘못된 누적 이동 제한')
                max_distance=min(max_distance,2*round_trip_distance+.4)
            limits=Limits(measured['robot_radius'],max_radius=data.get('max_radius',3.),
                max_duration=data.get('max_duration',600.),max_distance=max_distance,cycles=data.get('cycles',2),
                goal_timeout=90. if mode=='round_trip' else 45.)
            if mode=='round_trip' and round_trip_distance+limits.robot_radius+limits.margin>limits.max_radius:
                raise ValueError('출발점 반경은 목표 거리와 로봇 외곽·여유 공간보다 커야 합니다')
            if limits.max_radius>10 or limits.max_duration>3600 or limits.max_distance>500:
                raise ValueError('시험 범위는 반경 10m·시간 3600초·총 경로 500m 이하여야 합니다')
            task=str(data.get('task','자동 탐색 및 순회')).strip()
            multiplier=data.get('speed_multiplier',3)
            self.validate_speed(multiplier)
            self.speed_multiplier=multiplier
            if not 1<=len(task)<=240:raise ValueError('작업명을 1~240자로 입력하세요')
            self.owner=owner;self.error=None;self.fault_sensor_health=None;self.phase='starting';self.paused=False
            self.recording_expected=False;self.return_requested=False
            self.generation=getattr(self,'generation',0)+1
            self.results=queue.SimpleQueue();self.guard=None;self.handle=None;self.last_report=None;self.episode=None
            self.stop_event.clear();self.outcome='unfinished';self.mission=Mission(limits,round_trip_distance);self.grid=None
            self.public_limits={'max_radius_m':limits.max_radius,'max_duration_s':limits.max_duration,
                                'max_distance_m':limits.max_distance,'cycles':limits.cycles,'max_linear_m_s':.03*multiplier,'max_angular_rad_s':.15*multiplier,
                                'mode':mode,'target_distance_m':round_trip_distance}
            self.thread=threading.Thread(target=self.run,args=(measured,limits,task),daemon=True)
            self.thread.start()

    def request_stop(self,owner=None,emergency=False,outcome='unfinished'):
        if self.busy and not emergency and owner!=self.owner:raise ControlError('자율주행을 시작한 기기에서 조작하세요')
        if outcome not in ('unfinished','success','failure'):raise ValueError('잘못된 기록 결과')
        self.outcome=outcome;self.stop_event.set()
        with self.app.control.lock:
            if self.guard:self.guard.stop()
        if self.busy:self.phase='stopping'

    def pause(self,owner):
        if not self.busy or owner!=self.owner:raise ControlError('내 자율주행 세션이 없습니다')
        self.paused=True
        with self.app.control.lock:
            if self.guard:self.guard.stop()

    def return_home(self,owner):
        if not self.busy or owner!=self.owner or self.phase!='running':raise ControlError('복귀할 내 운행이 없습니다')
        self.return_requested=True;self.paused=False

    @staticmethod
    def validate_speed(multiplier):
        if type(multiplier) is not int or not 1<=multiplier<=3:raise ValueError('현재 자율주행 속도는 1~3배로 설정하세요')

    def set_speed(self,owner,multiplier):
        self.validate_speed(multiplier)
        with self.app.control.lock:
            if not self.busy or self.owner!=owner or self.phase!='running':raise ControlError('내 자율주행 운행 중에 속도를 변경하세요')
            self.speed_multiplier=multiplier
            self.public_limits.update(max_linear_m_s=.03*multiplier,max_angular_rad_s=.15*multiplier)
            if self.guard:self.guard.set_limits(.03*multiplier,.15*multiplier)
        self.app.recorder.event({'type':'autonomy_speed_changed','multiplier':multiplier,'max_linear_m_s':.03*multiplier})

    def start_recording(self,owner,task,slam=False):
        if not self.busy or owner!=self.owner or self.phase!='running':raise ControlError('내 자율주행이 실행된 뒤 기록하세요')
        recorder=self.app.recorder
        recorder.profile={**recorder.profile,'control_mode':'autonomous','patrol_limits':self.public_limits}
        episode=recorder.start(owner,task,slam=slam)
        if not self.busy or self.stop_event.is_set():
            recorder.finish(owner,'unfinished');raise ControlError('운행이 종료되어 기록도 종료했습니다')
        self.episode=episode;self.recording_expected=True
        recorder.event({'type':'autonomy_recording_started','mission':self.last_report})
        return episode

    def finish_recording(self,owner,outcome):
        if owner!=self.owner:raise ControlError('기록을 시작한 기기에서 종료하세요')
        self.recording_expected=False
        return self.app.recorder.finish(owner,outcome)

    def resume(self,owner):
        if not self.busy or owner!=self.owner or self.stop_event.is_set():raise ControlError('재개할 세션이 없습니다')
        if self.guard and self.guard.fault:raise ControlError('오류 후 자동 재활성화하지 않습니다. 종료 후 원인을 확인하세요')
        self.paused=False

    def tick(self):
        self.backend.poll()
        # Odom/TF/scan + tf2 subscriptions can exceed the 50 Hz application loop.
        # Drain a bounded batch so a continuously-ready sensor cannot starve /map
        # or action acknowledgements; planning itself stays in the other thread.
        if self.subscriptions:
            import rclpy
            deadline=time.monotonic()+.008
            for _ in range(8):
                if time.monotonic()>=deadline:break
                rclpy.spin_once(self.backend.node,timeout_sec=0)
        if self.guard is None or self.phase=='starting':return
        with self.health_lock:health=self.health.report(time.monotonic())
        ready=health['ready']
        if self.stop_event.is_set() or self.paused:self.guard.stop();return
        if self.recording_expected and (self.app.recorder.error or not self.app.recorder.active):
            self.error='기록 입력 또는 저장 중단';self.stop_event.set();self.guard.stop(self.error);return
        if time.monotonic()-self.last_planner>3 or (self.process and self.process.poll() is not None):
            self.error='계획 프로세스 응답 중단';self.stop_event.set();self.guard.stop(self.error);return
        self.guard.tick(ready)
        if self.guard.fault:
            self.fault_sensor_health=health;self.error=self.guard.fault;self.stop_event.set()

    def install_ros(self,sensor):
        import rclpy
        from rclpy.action import ActionClient
        from nav2_msgs.action import NavigateToPose
        from nav_msgs.msg import OccupancyGrid
        from geometry_msgs.msg import Twist
        from rosidl_runtime_py.utilities import get_message
        from rclpy.qos import QoSProfile,ReliabilityPolicy,DurabilityPolicy
        import tf2_ros
        node=self.backend.node
        self.tf=tf2_ros.Buffer();self.listener=tf2_ros.TransformListener(self.tf,node,spin_thread=False,qos=QoSProfile(depth=5))
        self.client=ActionClient(node,NavigateToPose,'/navigate_to_pose');self.goal_type=NavigateToPose
        self.health=SensorHealth(sensor)
        wheel_filter=self.config.get('patrol',{}).get('wheel_self_filter') is True
        if wheel_filter:
            if calibration(self.config)['robot_radius']<.20:raise ValueError('바퀴 반사 필터는 확인된 20cm 이상 외곽 설정이 필요합니다')
            from sensor_msgs.msg import LaserScan
            from rclpy.qos import qos_profile_sensor_data
            self.navigation_scan_topic='/scan_navigation'
            self.filtered_publisher=node.create_publisher(LaserScan,self.navigation_scan_topic,qos_profile_sensor_data)
        def observe(topic,message):
            with self.health_lock:self.health.observe(topic,message)
            if topic==sensor['scan_topic'] and self.filtered_publisher:
                import copy
                from scan_filter import wheel_self_returns
                filtered=copy.deepcopy(message)
                filtered.ranges=wheel_self_returns(message.ranges,message.angle_min,message.angle_increment)
                self.filtered_publisher.publish(filtered)
        for topic in (sensor['scan_topic'],sensor['odom_topic'],'/tf','/tf_static'):
            static=topic=='/tf_static'
            # Keep the newest continuous sample. A deep queue can leave scan and
            # odometry seconds apart while Nav2 starts on the Raspberry Pi.
            qos=QoSProfile(depth=100 if static else 1,reliability=ReliabilityPolicy.RELIABLE if static else ReliabilityPolicy.BEST_EFFORT,
                durability=DurabilityPolicy.TRANSIENT_LOCAL if static else DurabilityPolicy.VOLATILE)
            self.subscriptions.append(node.create_subscription(get_message(sensor['topics'][topic]),topic,lambda m,t=topic:observe(t,m),qos))
        def receive_map(message):
            try:
                q=message.info.origin.orientation
                if message.header.frame_id!='map' or abs(q.x)>1e-4 or abs(q.y)>1e-4 or abs(q.w*q.w+q.z*q.z-1)>.01:
                    raise ValueError('비평면/잘못된 지도 좌표')
                self.grid=Grid(message.info.width,message.info.height,message.info.resolution,tuple(message.data),
                    message.info.origin.position.x,message.info.origin.position.y,2*math.atan2(q.z,q.w),time.monotonic())
            except ValueError as error:self.error=str(error);self.stop_event.set()
        qos=QoSProfile(depth=1,reliability=ReliabilityPolicy.RELIABLE,durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.subscriptions.append(node.create_subscription(OccupancyGrid,'/map',receive_map,qos))
        def command(message):
            if self.guard and not self.paused and not self.stop_event.is_set():
                self.guard.receive((message.linear.x,message.linear.y,message.angular.z))
        self.subscriptions.append(node.create_subscription(Twist,'/nav2_cmd_vel',command,10))

    def read_pose(self,base_frame):
        import rclpy
        try:
            transform=self.tf.lookup_transform('map',base_frame,rclpy.time.Time())
            age=(self.backend.node.get_clock().now().nanoseconds-(transform.header.stamp.sec*10**9+transform.header.stamp.nanosec))/1e9
            if age < -.5 or age>self.mission.limits.pose_timeout:
                self.pose_error='TF age '+str(round(age,3));return None
            t,q=transform.transform.translation,transform.transform.rotation
            self.pose=(t.x,t.y,math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z)))
            return self.pose,time.monotonic()-max(0,age)
        except Exception as error:self.pose_error=str(error);return None

    def dispatch(self,command):
        token=command['token'];kind=command['action']
        generation=self.generation
        if kind=='send_goal':
            goal=command['goal'];message=self.goal_type.Goal()
            message.pose.header.frame_id='map';message.pose.header.stamp=self.backend.node.get_clock().now().to_msg()
            message.pose.pose.position.x=goal.x;message.pose.pose.position.y=goal.y
            message.pose.pose.orientation.z=math.sin(goal.yaw/2);message.pose.pose.orientation.w=math.cos(goal.yaw/2)
            self.app.recorder.event({'type':'autonomy_goal','token':token,'kind':goal.kind,'map_pose':[goal.x,goal.y,goal.yaw]})
            future=self.client.send_goal_async(message)
            def accepted(f):
                try:
                    handle=f.result()
                    if generation!=self.generation:
                        if handle.accepted:handle.cancel_goal_async()
                        return
                    if not handle.accepted:self.results.put((token,'failed'));return
                    self.handle=handle
                    if self.stop_event.is_set() or self.paused or self.mission.cancelling:
                        handle.cancel_goal_async()
                    def finished(result):
                        try:status=result.result().status
                        except Exception:status=6
                        if generation==self.generation:self.results.put((token,'succeeded' if status==4 else 'canceled' if status==5 else 'failed'))
                    handle.get_result_async().add_done_callback(finished)
                except Exception:self.results.put((token,'failed'))
            future.add_done_callback(accepted)
        elif kind=='cancel':
            if self.handle:self.handle.cancel_goal_async()
        elif kind=='stop':self.stop_event.set()

    def run(self,measured,limits,task):
        recorder=self.app.recorder;previous_profile=dict(recorder.profile);previous_slam_config=recorder.slam_config
        maintenance=None;log=None;lifecycle_clients={}
        try:
            from ament_index_python.packages import get_package_share_directory
            import yaml
            import sys
            sys.path.insert(0,str(ROOT/'tools'))
            from start_navigation import parameters
            from slam_map import stop_process
            maintenance=self.app.maintenance.allow();maintenance.__enter__()
            sensor=configuration(self.config.get('slam'),self.backend.output_parameters)
            if sensor['base_frame']!=measured['base_frame']:raise ValueError('보정과 바퀴 본체 프레임이 다릅니다')
            self.install_ros(sensor)
            navigation_sensor=dict(sensor)
            if self.navigation_scan_topic:
                navigation_sensor['scan_topic']=self.navigation_scan_topic
                extras={k:v for k,v in sensor['topics'].items() if k not in (sensor['scan_topic'],sensor['odom_topic'],'/tf','/tf_static')}
                extras[sensor['scan_topic']]='sensor_msgs/msg/LaserScan'
                recorder.slam_config=configuration({**sensor,'scan_topic':self.navigation_scan_topic,'extra_topics':extras})
            with self.app.control.lock:
                state=self.backend.status()
                if state.get('motor_ready') is True or state.get('other_publishers'):raise ValueError('다른 제어가 사용 중입니다')
                if self.backend.node.get_publishers_info_by_topic('/map'):
                    raise ValueError('기존 지도 발행자가 있습니다. 기존 SLAM/localization을 먼저 종료하세요')
                self.backend._ensure_base()
            self.run_dir=Path.home()/'.local/state/lekiwi-phone/patrol'/time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())
            self.run_dir.mkdir(parents=True,mode=0o700,exist_ok=False)
            (self.run_dir/'calibration.json').write_text(json.dumps(measured))
            template=Path(get_package_share_directory('nav2_bringup'))/'params/nav2_params.yaml'
            nav=parameters(yaml.safe_load(template.read_text()),Path('/unused-online-slam'),limits.robot_radius,navigation_sensor)
            nav.pop('amcl',None);nav.pop('map_server',None)
            for plugin in nav['planner_server']['ros__parameters'].get('planner_plugins',[]):
                nav['planner_server']['ros__parameters'].setdefault(plugin,{})['allow_unknown']=False
            for name in ('global_costmap','local_costmap'):
                nav[name][name]['ros__parameters']['track_unknown_space']=True
            if self.mission.round_trip_distance is not None:
                nav['controller_server']['ros__parameters']['general_goal_checker']['xy_goal_tolerance']=.05
                nav['controller_server']['ros__parameters']['FollowPath']['xy_goal_tolerance']=.05
            (self.run_dir/'nav2.yaml').write_text(yaml.safe_dump(nav))
            slam=yaml.safe_load((Path(get_package_share_directory('slam_toolbox'))/'config/mapper_params_online_async.yaml').read_text())
            slam['slam_toolbox']['ros__parameters'].update(use_sim_time=False,mode='mapping',scan_topic=navigation_sensor['scan_topic'],
                base_frame=sensor['base_frame'],odom_frame=sensor['odom_frame'],map_frame='map',map_update_interval=1.,resolution=.05)
            if self.mission.round_trip_distance is not None:
                slam['slam_toolbox']['ros__parameters'].update(minimum_travel_distance=.05,minimum_travel_heading=.05)
            (self.run_dir/'slam.yaml').write_text(yaml.safe_dump(slam))
            log=(self.run_dir/'stack.log').open('w')
            self.process=subprocess.Popen(['ros2','launch',str(ROOT/'tools/live_patrol_stack.py'),
                'params_file:='+str(self.run_dir/'nav2.yaml'),'slam_params_file:='+str(self.run_dir/'slam.yaml'),
                'calibration_file:='+str(self.run_dir/'calibration.json')],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            deadline=time.monotonic()+40
            from lifecycle_msgs.srv import GetState
            lifecycle_clients={name:self.backend.node.create_client(GetState,'/'+name+'/get_state')
                for name in ('planner_server','controller_server','smoother_server','behavior_server','bt_navigator')}
            lifecycle_pending={};lifecycle_active=set()
            while not self.stop_event.wait(.1):
                for name,client in lifecycle_clients.items():
                    pending=lifecycle_pending.get(name)
                    if pending is not None and pending.done():
                        response=pending.result()
                        if response is not None and response.current_state.id==3:lifecycle_active.add(name)
                        else:lifecycle_active.discard(name)
                        del lifecycle_pending[name]
                    if name not in lifecycle_active and name not in lifecycle_pending and client.service_is_ready():
                        lifecycle_pending[name]=client.call_async(GetState.Request())
                with self.health_lock:ready=self.health.report(time.monotonic())['ready']
                if self.grid and ready and self.read_pose(sensor['base_frame']) and self.client.server_is_ready() and len(lifecycle_active)==len(lifecycle_clients):break
                if self.process.poll() is not None or time.monotonic()>deadline:
                    with self.health_lock:missing=self.health.report(time.monotonic())['missing']
                    raise ValueError('SLAM·센서·TF·Nav2 준비 실패: '+json.dumps({'map':self.grid is not None,
                        'sensor_missing':missing,'pose_error':getattr(self,'pose_error',None),
                        'nav2_action_ready':self.client.server_is_ready(),'nav2_inactive_nodes':sorted(set(lifecycle_clients)-lifecycle_active)},ensure_ascii=False))
            if self.stop_event.is_set():return
            self.guard=NavigationGuard(self.backend)
            self.guard.set_limits(.03*self.speed_multiplier,.15*self.speed_multiplier)
            self.phase='running';self.last_planner=time.monotonic()
            while not self.stop_event.wait(.2):
                while not self.results.empty():
                    token,outcome=self.results.get();self.mission.result(token,outcome)
                    recorder.event({'type':'autonomy_goal_result','token':token,'outcome':outcome})
                now=time.monotonic();measured_pose=self.read_pose(sensor['base_frame'])
                with self.health_lock:ready=self.health.report(now)['ready']
                if self.return_requested:
                    self.return_requested=False;command=self.mission.halt('returning','operator_return',now)
                elif self.paused and self.mission.state!='paused':command=self.mission.pause(now)
                elif self.paused:command=self.mission.step(self.grid,self.pose or (0.,0.,0.),now,sensors_ready=ready)
                else:
                    if self.mission.state=='paused':self.mission.resume()
                    pose,received=measured_pose if measured_pose else (self.pose or (0.,0.,0.),now-10)
                    command=self.mission.step(self.grid,pose,now,pose_received_at=received,sensors_ready=ready)
                self.dispatch(command);self.last_planner=time.monotonic();self.last_report=self.mission.report()
                if self.mission.state in ('complete','blocked','fault','stopped'):
                    self.stop_event.set()
        except Exception as error:self.error=str(error)
        finally:
            self.stop_event.set();self.phase='stopping'
            with self.app.control.lock:
                if self.guard:self.guard.stop()
            if self.handle:
                try:self.handle.cancel_goal_async()
                except Exception:pass
            if self.process is not None:stop_process(self.process)
            self.process=None
            if self.mission:self.last_report=self.mission.report()
            if recorder.active and recorder.owner==self.owner:
                recorder.event({'type':'autonomy_finished','mission':self.last_report,'error':self.error})
                try:recorder.finish(self.owner,self.outcome)
                except Exception as error:self.error='기록 종료 확인 실패: '+str(error)
            recorder.profile=previous_profile
            recorder.slam_config=previous_slam_config
            for sub in self.subscriptions:self.backend.node.destroy_subscription(sub)
            for client in lifecycle_clients.values():self.backend.node.destroy_client(client)
            self.subscriptions=[]
            if self.filtered_publisher:self.backend.node.destroy_publisher(self.filtered_publisher)
            self.filtered_publisher=None;self.navigation_scan_topic=None
            if hasattr(self,'client'):self.client.destroy()
            if hasattr(self,'listener'):self.listener.unregister()
            if log:log.close()
            if maintenance:maintenance.__exit__(None,None,None)
            self.phase='fault' if self.error else 'idle'
