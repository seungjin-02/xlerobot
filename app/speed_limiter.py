"""Keep wheel ratios when the requested body speed exceeds output capacity."""
import math

def limit_motion(motion, parameters):
    x, y, z = motion
    p = parameters
    yaw = p.get('kinematics_frame_yaw', 0.)
    x_origin = x - z * p.get('kinematics_frame_y', 0.)
    y_origin = y + z * p.get('kinematics_frame_x', 0.)
    local_x = math.cos(yaw) * x_origin + math.sin(yaw) * y_origin
    local_y = -math.sin(yaw) * x_origin + math.cos(yaw) * y_origin
    radius, base = p['wheel_radius'], p['base_radius']
    wheels = [(-math.sin(a) * local_x - math.cos(a) * local_y + base * z) / radius
              for a in (2 * math.pi / 3, 0., 4 * math.pi / 3)]
    envelope = min(p['max_wheel_speed'], p['speed_tick_limit'] / p['speed_tick_scale'])
    peak = max(abs(w) for w in wheels)
    ratio = min(1., envelope / peak) if peak else 1.
    return tuple(v * ratio for v in motion)


def slew_motion(current, target, dt, linear_acceleration=.6, angular_acceleration=.4):
    """Ramp direction/velocity changes; release-to-zero bypasses this function."""
    dx, dy = target[0] - current[0], target[1] - current[1]
    distance = math.hypot(dx, dy)
    fraction = min(1., linear_acceleration * dt / distance) if distance else 1.
    dz = target[2] - current[2]
    angular_step = max(-angular_acceleration * dt, min(angular_acceleration * dt, dz))
    return (current[0] + dx * fraction, current[1] + dy * fraction, current[2] + angular_step)
