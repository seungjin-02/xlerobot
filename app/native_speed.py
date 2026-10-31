"""Read the native operator's live speed policy without launching a driver.

Never invent a faster fallback when the native backend is unavailable.
"""
import math


def native_speed_policy(status, pad='drive'):
    if pad not in ('drive', 'mapping'):
        raise ValueError('Unknown speed pad')
    teleop = status.get('teleop') or {}
    policy = (teleop.get('pads') or {}).get(pad) or {}
    levels = policy.get('levels')
    maximum = policy.get('max_level')
    if not isinstance(levels, list) or not levels or type(maximum) is not int or maximum != len(levels)-1:
        return {'available': False, 'levels': [], 'reason': '로보시지 속도 정책 응답 대기'}
    for pair in levels:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in pair):
            return {'available': False, 'levels': [], 'reason': '속도 정책 응답 오류'}
    return {'available': True, 'pad': pad, 'levels': [list(p) for p in levels],
            'max_level': maximum, 'max_linear_y': policy.get('max_linear_y'),
            'source': (teleop.get('limits') or {}).get('source', 'unknown'),
            'is_allowed': teleop.get('is_allowed') is True,
            'reason': teleop.get('blocked_reason')}


def teleop_message(status, pad, level, x, y, yaw):
    policy = native_speed_policy(status, pad)
    if not policy['available']:
        raise ValueError(policy['reason'])
    if type(level) is not int or not 0 <= level <= policy['max_level']:
        raise ValueError('속도 단계를 다시 선택하세요')
    axes = (x, y, yaw)
    if any(type(v) not in (int, float) or not math.isfinite(v) or not -1 <= v <= 1 for v in axes):
        raise ValueError('Invalid control axes')
    # Native backend owns lease, timeout, vector normalization and wheel limits.
    return dict(type='teleop', pad=pad, level=level, x=x, y=y, yaw=yaw)
