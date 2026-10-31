"""Nav2 lifecycle nodes; their velocity output goes only to the guarded input."""
import json
from pathlib import Path
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def nodes(context):
    params = LaunchConfiguration('params_file').perform(context)
    names = ['map_server','amcl','planner_server','controller_server','smoother_server','behavior_server','bt_navigator']
    packages = ['nav2_map_server','nav2_amcl','nav2_planner','nav2_controller','nav2_smoother','nav2_behaviors','nav2_bt_navigator']
    mode = LaunchConfiguration('localization_mode').perform(context)
    if mode not in ('saved_map','slam'): raise ValueError('Unknown localization mode')
    if mode == 'slam': names,packages = names[2:],packages[2:]
    result = []
    for name,package in zip(names,packages):
        result.append(Node(package=package,executable=name,name=name,output='screen',parameters=[params],
            remappings=[('cmd_vel','/nav2_cmd_vel')]))
    result.append(Node(package='nav2_lifecycle_manager',executable='lifecycle_manager',
        name='lekiwi_nav_lifecycle_manager',output='screen',
        parameters=[{'autostart':True,'use_sim_time':False,'node_names':names,'bond_timeout':4.0}]))
    return result


def generate_launch_description():
    return LaunchDescription([DeclareLaunchArgument('params_file'),
        DeclareLaunchArgument('localization_mode',default_value='saved_map'),OpaqueFunction(function=nodes)])
