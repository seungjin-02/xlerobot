#!/usr/bin/env python3
"""Prepare or explicitly start low-speed Nav2 navigation on a verified robot.

Default is preparation only. --enable-motion permits motor activation on a Nav2
goal; do not use it without physical clearance, emergency stop and calibration.
"""
import argparse
import copy
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request
import urllib.error

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from slam import configuration, SensorHealth, atomic_json
from navigation_guard import NavigationGuard
from slam_map import stop_process


def parameters(template, map_path, radius, config, initial_pose=None):
    if not math.isfinite(radius) or not .05 <= radius <= 2: raise ValueError('실측 로봇 외접 반경 0.05~2m가 필요합니다')
    value = copy.deepcopy(template)
    for key,node in value.items():
        if isinstance(node,dict) and 'ros__parameters' in node: node['ros__parameters']['use_sim_time'] = False
    amcl = value['amcl']['ros__parameters']
    amcl.update(base_frame_id=config['base_frame'],odom_frame_id=config['odom_frame'],global_frame_id='map',
                scan_topic=config['scan_topic'],robot_model_type='nav2_amcl::OmniMotionModel',set_initial_pose=initial_pose is not None)
    if initial_pose:
        if not all(math.isfinite(v) for v in initial_pose): raise ValueError('초기 위치가 잘못됐습니다')
        amcl['initial_pose'] = dict(zip(('x','y','yaw'),initial_pose)); amcl['initial_pose']['z'] = 0.
    value.setdefault('map_server',{'ros__parameters':{}})['ros__parameters']['yaml_filename'] = str(map_path)
    for key in ('bt_navigator','behavior_server'):
        value[key]['ros__parameters'].update(robot_base_frame=config['base_frame'],odom_topic=config['odom_topic'])
    value['behavior_server']['ros__parameters'].update(global_frame='map',local_frame=config['odom_frame'],enable_stamped_cmd_vel=False)
    controller = value['controller_server']['ros__parameters']
    controller.update(odom_topic=config['odom_topic'],controller_frequency=20.,enable_stamped_cmd_vel=False,
                      min_x_velocity_threshold=.001,min_y_velocity_threshold=.001,min_theta_velocity_threshold=.001)
    controller['FollowPath'] = dict(plugin='dwb_core::DWBLocalPlanner',min_vel_x=-.1,min_vel_y=-.1,
        max_vel_x=.1,max_vel_y=.1,max_vel_theta=.5,min_speed_xy=0.,max_speed_xy=.1,min_speed_theta=0.,
        acc_lim_x=.2,acc_lim_y=.2,acc_lim_theta=.4,decel_lim_x=-.2,decel_lim_y=-.2,decel_lim_theta=-.4,
        vx_samples=9,vy_samples=9,vtheta_samples=15,sim_time=1.7,linear_granularity=.05,
        angular_granularity=.025,transform_tolerance=.2,xy_goal_tolerance=.1,trans_stopped_velocity=.02,
        short_circuit_trajectory_evaluation=True,stateful=True,
        critics=['RotateToGoal','Oscillation','BaseObstacle','GoalAlign','PathAlign','PathDist','GoalDist'],
        **{'BaseObstacle.scale':.02,'PathAlign.scale':32.,'PathAlign.forward_point_distance':.1,
           'GoalAlign.scale':24.,'GoalAlign.forward_point_distance':.1,'PathDist.scale':32.,
           'GoalDist.scale':24.,'RotateToGoal.scale':32.,'RotateToGoal.slowing_factor':5.,'RotateToGoal.lookahead_time':-1.})
    controller['general_goal_checker'].update(xy_goal_tolerance=.1,yaw_goal_tolerance=.15)
    for key,frame in (('local_costmap',config['odom_frame']),('global_costmap','map')):
        costmap = value[key][key]['ros__parameters']
        costmap.update(global_frame=frame,robot_base_frame=config['base_frame'],robot_radius=radius,use_sim_time=False)
        costmap.pop('footprint',None)
        for layer in ('obstacle_layer','voxel_layer'):
            if layer in costmap and 'scan' in costmap[layer]: costmap[layer]['scan']['topic'] = config['scan_topic']
    return value


def require_phone_stopped():
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with client.open('http://127.0.0.1:8090/health',timeout=2): pass
    except urllib.error.HTTPError:
        raise ValueError('8090 서버가 실행 중입니다. 폰 서비스를 먼저 중지하세요') from None
    except urllib.error.URLError as error:
        if isinstance(error.reason,ConnectionRefusedError): return
        raise ValueError('폰 서비스 정지 상태를 확인할 수 없습니다') from None
    raise ValueError('폰 서비스를 먼저 중지하세요. 수동 조종과 자율주행을 동시에 실행하지 않습니다')


def run_navigation(config, params_path):
    import rclpy
    from geometry_msgs.msg import Twist
    from rosidl_runtime_py.utilities import get_message
    from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
    from ros_backend import RosBackend
    from maintenance import Maintenance
    require_phone_stopped()
    backend = RosBackend(config['profile'],config.get('workspace'),node_name='lekiwi_navigation_guard')
    guard = NavigationGuard(backend)
    sensor_config = configuration(config.get('slam'),backend.output_parameters)
    health = SensorHealth(sensor_config)
    process = None; stopped = False; subscriptions = []
    def stop(*_):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGINT,stop); signal.signal(signal.SIGTERM,stop)
    try:
        with Maintenance().allow():
            # This starts/validates the known torque-disabled base, not motor power.
            backend._ensure_base()
            backend.poll()
            if backend.ready is not False or backend.others: raise ValueError('다른 제어/모터 상태를 확인하세요')
            subscriptions.append(backend.node.create_subscription(Twist,'/nav2_cmd_vel',
                lambda m:guard.receive((m.linear.x,m.linear.y,m.angular.z)),10))
            for name in (sensor_config['scan_topic'],sensor_config['odom_topic'],'/tf','/tf_static'):
                qos = QoSProfile(depth=100,reliability=ReliabilityPolicy.RELIABLE if name=='/tf_static' else ReliabilityPolicy.BEST_EFFORT,
                    durability=DurabilityPolicy.TRANSIENT_LOCAL if name=='/tf_static' else DurabilityPolicy.VOLATILE)
                subscriptions.append(backend.node.create_subscription(get_message(sensor_config['topics'][name]),name,
                    lambda m, topic=name:health.observe(topic,m),qos))
            deadline = time.monotonic()+10
            while time.monotonic()<deadline and not health.report(time.monotonic())['ready']:
                backend.poll(); time.sleep(.01)
            if not health.report(time.monotonic())['ready']: raise ValueError('LiDAR/odometry/TF 입력이 준비되지 않았습니다')
            process = subprocess.Popen(['ros2','launch',str(Path(__file__).with_name('navigation_launch.py')),
                'params_file:='+str(params_path)],start_new_session=True)
            print('Nav2 시작. RViz에서 초기 위치를 지정한 뒤 목표를 보내세요. Ctrl+C는 정지/비활성화를 요청합니다.',flush=True)
            while not stopped and process.poll() is None and not guard.fault:
                require_phone_stopped()
                backend.poll()
                # Count every publisher, including duplicate node names.
                if len(backend.node.get_publishers_info_by_topic('/cmd_vel')) > 1:
                    guard.stop('다른 /cmd_vel 발행자 발견'); break
                guard.tick(health.report(time.monotonic())['ready'])
                time.sleep(.02)
            if guard.fault: raise ValueError(guard.fault)
            if not stopped and process.returncode: raise ValueError('Nav2 프로세스 종료')
    finally:
        guard.stop(); stop_process(process); backend.close()


def main():
    import yaml
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--map',type=Path,required=True)
    parser.add_argument('--robot-radius',type=float,required=True,help='실측 외접 반경(m), 팔/돌출부 포함')
    parser.add_argument('--config',type=Path,default=Path.home()/'.config/lekiwi-phone/config.json')
    parser.add_argument('--output',type=Path,required=True,help='새 Nav2 설정 출력 폴더')
    parser.add_argument('--initial-pose',nargs=3,type=float,metavar=('X','Y','YAW'))
    parser.add_argument('--enable-motion',action='store_true')
    args = parser.parse_args()
    try:
        from ament_index_python.packages import get_package_share_directory
        config = json.loads(args.config.read_text())
        # Only wheel/sensor settings are copied; PIN/AP credentials never enter output.
        import yaml
        wheel = yaml.safe_load(Path(config['profile']).read_text())['lekiwi_node']['ros__parameters']
        sensor_config = configuration(config.get('slam'),wheel)
        map_path = args.map.resolve()
        map_meta = yaml.safe_load(map_path.read_text())
        if not (map_path.parent/map_meta['image']).is_file(): raise ValueError('지도 이미지가 없습니다')
        template = Path(get_package_share_directory('nav2_bringup'))/'params/nav2_params.yaml'
        params = parameters(yaml.safe_load(template.read_text()),map_path,args.robot_radius,sensor_config,args.initial_pose)
        args.output.mkdir(mode=0o700)
        path = (args.output/'nav2.yaml').resolve(); path.write_text(yaml.safe_dump(params))
        atomic_json(args.output/'navigation-plan.json',{'map':str(map_path),'robot_radius':args.robot_radius,
            'max_linear_request_m_s':.1,'max_angular_request_rad_s':.5,'command_timeout_s':.3,
            'motor_activation_requested':args.enable_motion,'physical_navigation_tested':False})
        if args.enable_motion:
            os.environ['ROS_DOMAIN_ID']='42'; os.environ['ROS_AUTOMATIC_DISCOVERY_RANGE']='LOCALHOST'
            run_navigation(config,path)
        else: print('준비 완료. 모터를 활성화하지 않았습니다. 현장 점검 후 새 --output과 --enable-motion으로 실행하세요.')
        return 0
    except (OSError,ValueError,KeyError,ImportError) as error:
        print('자율주행 준비/실행 실패: '+str(error),file=sys.stderr); return 1


if __name__ == '__main__': raise SystemExit(main())
