#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID -eq 0 ]]; then echo '로봇 사용자 계정에서 실행하세요. 필요한 단계만 sudo를 사용합니다.' >&2; exit 1; fi
source /etc/os-release
if [[ "$ID" != ubuntu || "$VERSION_ID" != 24.04 ]]; then echo '이 패키지는 Ubuntu 24.04 + ROS 2 Jazzy용입니다. OS를 확인하세요.' >&2; exit 1; fi
export LANG=C.UTF-8
sudo -v
sudo apt-get update
sudo apt-get install -y ca-certificates curl software-properties-common
if [[ ! -f /opt/ros/jazzy/setup.bash ]]; then
    sudo add-apt-repository -y universe
    temporary_dir="$(mktemp -d)"
    trap 'rm -rf "$temporary_dir"' EXIT
    curl -fsSL --retry 2 https://api.github.com/repos/ros-infrastructure/ros-apt-source/releases/latest -o "$temporary_dir/release.json"
    apt_source_version="$(python3 - "$temporary_dir/release.json" <<'PY'
import json,sys,re
v=json.load(open(sys.argv[1]))['tag_name']
if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',v): raise SystemExit('Unexpected official ROS apt-source release tag')
print(v)
PY
)"
    curl -fL --retry 2 "https://github.com/ros-infrastructure/ros-apt-source/releases/download/$apt_source_version/ros2-apt-source_$apt_source_version.noble_all.deb" -o "$temporary_dir/ros2-apt-source.deb"
    sudo dpkg -i "$temporary_dir/ros2-apt-source.deb"
    sudo apt-get update
fi
sudo apt-get install -y ros-jazzy-ros-base ros-jazzy-rclpy ros-jazzy-tf2-ros \
    python3-colcon-common-extensions python3-yaml python3-opencv python3-pil python3-qrcode \
    build-essential cmake network-manager iw \
    ros-jazzy-rosbag2-py ros-jazzy-rosbag2-storage-default-plugins
sudo usermod -aG dialout,video "$(id -un)"
sudo loginctl enable-linger "$(id -un)"
echo '시스템 준비 완료. 새 그룹 권한 적용을 위해 설치 완료 후 1회 재부팅하세요.'
