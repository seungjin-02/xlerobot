"""Live SLAM + guarded Nav2. Does not launch or enable any motor driver."""
from pathlib import Path
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
import json


def nodes(context):
    nav=LaunchConfiguration('params_file').perform(context)
    slam=LaunchConfiguration('slam_params_file').perform(context)
    calibration=json.loads(Path(LaunchConfiguration('calibration_file').perform(context)).read_text())
    result=[]
    if not calibration.get('external_lidar_tf',False):
        pose=calibration['lidar_transform']
        args=[]
        for key in ('x','y','z','roll','pitch','yaw'):args.extend(['--'+key,str(pose[key])])
        args.extend(['--frame-id',calibration['base_frame'],'--child-frame-id',calibration['lidar_frame']])
        result.append(Node(package='tf2_ros',executable='static_transform_publisher',name='lekiwi_measured_lidar_tf',arguments=args))
    result.extend([
        IncludeLaunchDescription(PythonLaunchDescriptionSource(str(Path(get_package_share_directory('slam_toolbox'))/'launch/online_async_launch.py')),
            launch_arguments={'slam_params_file':slam,'use_sim_time':'false','autostart':'true'}.items()),
        IncludeLaunchDescription(PythonLaunchDescriptionSource(str(Path(__file__).with_name('navigation_launch.py'))),
            launch_arguments={'params_file':nav,'localization_mode':'slam'}.items())])
    return result


def generate_launch_description():
    return LaunchDescription([DeclareLaunchArgument('params_file'),DeclareLaunchArgument('slam_params_file'),
        DeclareLaunchArgument('calibration_file'),OpaqueFunction(function=nodes)])
