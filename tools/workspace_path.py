"""Resolve the install workspace without changing robot configuration."""
import argparse
import json
from pathlib import Path


def workspace_path(config_dir, explicit=None):
    value = explicit
    if value is None:
        config = Path(config_dir).expanduser() / 'config.json'
        if config.exists():
            settings = json.loads(config.read_text())
            if not isinstance(settings, dict):
                raise ValueError('invalid config')
            value = settings.get('workspace')
    if value is None:
        return (Path.home() / '.local/share/lekiwi-phone/ros_ws').resolve()
    if not isinstance(value, str) or not value.strip() or '\n' in value or '\r' in value:
        raise ValueError('invalid workspace')
    return Path(value).expanduser().resolve()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config-dir', type=Path, required=True)
    parser.add_argument('--workspace')
    args = parser.parse_args()
    try:
        print(workspace_path(args.config_dir, args.workspace))
    except (OSError, ValueError):
        parser.exit(1, '기존 설정/workspace 경로를 읽을 수 없습니다. 설정을 보존하고 확인하세요.\n')


if __name__ == '__main__':
    main()
