"""Read-only idle checks shared by the exclusive web controller switcher."""

MODES = ('custom', 'factory')
ACTIVE = {'starting', 'running', 'stopping', 'external', 'active', 'recording'}


def require_idle(mode, status):
    if mode not in MODES or not isinstance(status, dict):
        raise ValueError('조작기 상태를 확인할 수 없습니다')
    if mode == 'custom':
        if not all(k in status for k in ('armed', 'autonomy', 'recording')):
            raise ValueError('새 웹앱 상태 형식이 다릅니다')
        if status['armed'] is not False or status.get('motor_ready') is True:
            raise ValueError('조종 종료 후 전환하세요')
        if status['autonomy'].get('busy') is not False:
            raise ValueError('자율주행을 종료한 뒤 전환하세요')
        if status['recording'].get('active') is not False:
            raise ValueError('기록을 저장·종료한 뒤 전환하세요')
        if any(status.get('output_motion', [0, 0, 0])):
            raise ValueError('이동 출력이 남아 있습니다')
        return
    processes = status.get('processes')
    if not isinstance(processes, dict) or not {'bringup', 'mapping', 'navigation'} <= processes.keys():
        raise ValueError('기존 조작기의 기능 상태를 확인할 수 없습니다')
    for name, process in processes.items():
        allowed = ('stopped', 'idle', 'failed', 'exited', 'succeeded') if name == 'save_map' else ('stopped', 'idle', 'failed', 'exited')
        if not isinstance(process, dict) or process.get('state') not in allowed:
            raise ValueError('기존 조작기에서 로봇·지도·주행·저장 기능을 먼저 종료하세요: ' + name)
    motor = status.get('motor')
    arm = status.get('teleop_arm')
    if not isinstance(motor, dict) or not isinstance(arm, dict):
        raise ValueError('기존 모터·팔 상태를 확인할 수 없습니다')
    if motor.get('ready') is True or motor.get('is_powered_by_us'):
        raise ValueError('기존 조작기의 바퀴 전원을 먼저 끄세요')
    if (status.get('control') or {}).get('holder'):
        raise ValueError('기존 조종 권한을 먼저 해제하세요')
    if any(arm.get(k) for k in ('arm_ready', 'is_session_active', 'is_torque_maybe_on')):
        raise ValueError('기존 조작기의 팔 조종·토크를 먼저 종료하세요')
    if (status.get('zmq_host') or {}).get('session') == 'active':
        raise ValueError('연결된 PC 조종 세션을 먼저 종료하세요')
    def check(value):
        if isinstance(value, dict):
            if value.get('state') in ACTIVE or value.get('is_recording') or value.get('recording') is True:
                raise ValueError('기존 탐색·팔·보정 작업을 먼저 종료하세요')
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)
    for key in ('calibration', 'exploration'):
        check(status.get(key))
