#!/usr/bin/env bash
# PC mapping/navigation dependencies; never starts a robot, changes AP or services.
set -euo pipefail
source /etc/os-release
if [[ "$ID" != ubuntu || "$VERSION_ID" != 24.04 || ! -f /opt/ros/jazzy/setup.bash ]]; then
    echo 'Ubuntu 24.04 + ROS 2 Jazzy 환경을 먼저 준비하세요.' >&2
    exit 1
fi
sudo apt-get update
sudo apt-get install -y ros-jazzy-rosbag2-py ros-jazzy-rosbag2-storage-default-plugins \
    ros-jazzy-slam-toolbox ros-jazzy-navigation2 ros-jazzy-nav2-bringup python3-yaml
