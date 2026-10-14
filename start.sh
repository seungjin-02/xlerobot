#!/usr/bin/env bash
set -eo pipefail
config_path="${1:-$HOME/.config/lekiwi-phone/config.json}"
mapfile -t runtime_paths < <(/usr/bin/python3 - "$config_path" <<'PY'
import json,sys
from pathlib import Path
c=json.loads(Path(sys.argv[1]).read_text());print(c['ros_setup']);print(c['workspace_setup'])
PY
)
source "${runtime_paths[0]}"
source "${runtime_paths[1]}"
export ROS_DOMAIN_ID=42
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
exec /usr/bin/python3 "$(dirname "$(readlink -f "$0")")/app/server.py" --config "$config_path" --port 8090
