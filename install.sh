#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$(readlink -f "$0")")"
if [[ $EUID -eq 0 ]]; then echo 'sudo bash install.sh 대신 로봇 사용자 계정에서 bash install.sh를 실행하세요.' >&2; exit 1; fi
setup_arguments=()
workspace_path=""
config_dir="$HOME/.config/lekiwi-phone"
skip_dependencies=false
specified_workspace=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-dependencies) skip_dependencies=true; shift ;;
        --workspace) workspace_path="$2"; specified_workspace=true; setup_arguments+=("$1" "$2"); shift 2 ;;
        --config-dir) config_dir="$2"; setup_arguments+=("$1" "$2"); shift 2 ;;
        *) setup_arguments+=("$1"); shift ;;
    esac
done
for value in "${setup_arguments[@]}"; do
    if [[ "$value" == --dry-run ]]; then exec /usr/bin/python3 setup_robot.py "${setup_arguments[@]}"; fi
done
workspace_arguments=(--config-dir "$config_dir")
if [[ "$specified_workspace" == true ]]; then workspace_arguments+=(--workspace "$workspace_path"); fi
workspace_path="$(/usr/bin/python3 tools/workspace_path.py "${workspace_arguments[@]}")"
if [[ "$skip_dependencies" == false ]]; then bash prepare-system.sh; fi
if [[ ! -f /opt/ros/jazzy/setup.bash ]]; then echo 'ROS 2 Jazzy가 없습니다. --skip-dependencies 없이 설치하세요.' >&2; exit 1; fi
source /opt/ros/jazzy/setup.bash
if [[ "$specified_workspace" == false ]]; then
    mkdir -p "$workspace_path/src"
    cp -a drivers/lekiwi_node "$workspace_path/src/"
    export CMAKE_BUILD_PARALLEL_LEVEL=2 MAKEFLAGS=-j2
    (cd "$workspace_path" && colcon build --executor sequential --packages-select lekiwi_node --cmake-args -DBUILD_TESTING=OFF)
else
    test -f "$workspace_path/install/setup.bash"
fi
chmod +x start.sh
exec /usr/bin/python3 setup_robot.py --workspace "$workspace_path" "${setup_arguments[@]}"
