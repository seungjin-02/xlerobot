"""Latched directional control with bounded disconnect continuation."""
import math
import secrets
import threading
import time

DIRECTIONS = {'forward': (1, 0, 0), 'back': (-1, 0, 0), 'left': (0, 1, 0),
              'right': (0, -1, 0), 'turn_left': (0, 0, 1), 'turn_right': (0, 0, -1),
              'idle': (0, 0, 0)}

class ControlError(Exception):
    pass

class Controller:
    def __init__(self, backend, clock=time.monotonic, grace_seconds=10.):
        self.backend, self.clock = backend, clock
        self.lock = threading.RLock()
        self.grace_seconds = grace_seconds
        self.output_motion = (0., 0., 0.)
        self.last_tick = self.clock()
        self.owner = self.lease = None
        self.seq = -1
        self.last_packet = self.last_activity = 0
        self.hold = None
        self.hold_started = 0
        self.expired_holds = set()
        self.desired_motion = self.motion = (0., 0., 0.)
        self.reason = '조종 중지 상태'
        self.cleanup_error = None

    def arm(self, owner):
        with self.lock:
            if self.owner:
                raise ControlError('이미 조종 중입니다. 먼저 정지하세요.')
            status = self.backend.status()
            if status.get('motor_ready'):
                raise ControlError('다른 제어에서 모터가 켜져 있습니다. 해당 조종을 먼저 종료하세요.')
            if status.get('other_publishers', 0):
                raise ControlError('다른 조종 프로그램이 실행 중입니다.')
            self.backend.arm()
            status = self.backend.status()
            if not status.get('motor_ready') or not status.get('available') or status.get('other_publishers'):
                self.backend.disarm()
                raise ControlError('바퀴 제어 준비를 확인하지 못했습니다.')
            self.owner, self.lease = owner, secrets.token_urlsafe(24)
            self.seq = -1
            self.last_packet = self.last_activity = self.clock()
            self.hold = None
            self.expired_holds.clear()
            self.desired_motion = self.motion = self.output_motion = (0., 0., 0.)
            self.last_tick = self.clock()
            self.reason = '방향 버튼을 한 번 눌러 켜고 다시 눌러 끄세요'
            self.cleanup_error = None
            return self.lease

    def command(self, owner, lease, seq, direction, speed, hold):
        with self.lock:
            if owner != self.owner or not self.lease or not secrets.compare_digest(str(lease), self.lease):
                raise ControlError('조종 권한이 만료됐습니다. 다시 시작하세요.')
            if not isinstance(seq, int) or isinstance(seq, bool) or seq <= self.seq:
                raise ControlError('오래된 명령을 거부했습니다.')
            if direction not in DIRECTIONS or not isinstance(speed, (int, float)) or isinstance(speed, bool) or not math.isfinite(speed) or not 1 / 30 <= speed <= 1:
                raise ControlError('유효하지 않은 조종 명령입니다.')
            if direction != 'idle' and (not isinstance(hold, str) or not 1 <= len(hold) <= 64):
                raise ControlError('방향 선택 식별자가 필요합니다.')
            now = self.clock()
            if now - self.last_packet >= self.grace_seconds:
                self._stop('연결 끊김으로 정지했습니다')
                raise ControlError(self.reason)
            self.seq, self.last_packet = seq, now
            if direction == 'idle':
                if self.hold:
                    self.expired_holds.add(self.hold)
                self.hold = None
                self.desired_motion = self.motion = self.output_motion = (0., 0., 0.)
                self.backend.publish(self.output_motion)
                return
            if hold in self.expired_holds:
                self.desired_motion = self.motion = self.output_motion = (0., 0., 0.)
                self.backend.publish(self.output_motion)
                return
            if hold != self.hold:
                if self.hold:
                    self.expired_holds.add(self.hold)
                if len(self.expired_holds) > 1000:
                    self._stop('조종 세션을 다시 시작하세요')
                    raise ControlError(self.reason)
                self.hold, self.hold_started = hold, now
            x, y, z = DIRECTIONS[direction]
            self.desired_motion = (x*.9*speed, y*.9*speed, z*4.5*speed)
            self.motion = (x * min(.9 * speed, self.backend.status().get('max_linear', .03)), y * min(.9 * speed, self.backend.status().get('max_linear', .03)), z * min(4.5 * speed, self.backend.status().get('max_angular', .1)))
            self.last_activity = now

    def stop(self, owner=None, emergency=False):
        with self.lock:
            if self.owner and (emergency or self.owner == owner):
                self._stop('정지했습니다')

    def _stop(self, reason):
        # Invalidate lease before I/O, even when a backend call fails.
        self.owner = self.lease = None
        self.desired_motion = self.motion = self.output_motion = (0., 0., 0.)
        self.hold = None
        self.reason = reason
        errors = []
        try:
            self.backend.publish(self.motion)
        except Exception as e:
            errors.append(str(e))
        try:
            self.backend.disarm()
        except Exception as e:
            errors.append(str(e))
        self.cleanup_error = '; '.join(errors) or None
        if errors:
            self.reason = '정지 확인 실패: 전원을 차단하세요'

    def tick(self):
        with self.lock:
            self.backend.poll()
            if not self.owner:
                return
            now = self.clock()
            status = self.backend.status()
            if not status.get('available') or not status.get('motor_ready') or status.get('other_publishers'):
                self._stop('제어 상태 변경으로 정지했습니다')
            elif now - self.last_packet >= self.grace_seconds:
                self._stop('연결 끊김으로 정지했습니다')
            elif now - self.last_activity > 15:
                self._stop('15초 동안 조작이 없어 종료했습니다')
            else:
                from speed_limiter import slew_motion
                dt = min(.1, max(0., now - self.last_tick))
                if now - self.last_packet <= .6:
                    target = self.backend.limit_motion(self.motion) if hasattr(self.backend, 'limit_motion') else self.motion
                    self.output_motion = slew_motion(self.output_motion, target, dt)
                published = self.backend.publish(self.output_motion)
                if published is not None: self.output_motion = tuple(published)
            self.last_tick = now

    def status(self, owner):
        with self.lock:
            return {**self.backend.status(), 'armed': bool(self.owner), 'mine': self.owner == owner and bool(self.owner),
                    'reason': self.reason, 'cleanup_error': self.cleanup_error,
                    'motion': self.motion, 'requested_motion': self.desired_motion, 'output_motion': self.output_motion, 'reconnecting': bool(self.owner) and self.clock() - self.last_packet > .6, 'max_linear': min(.9, self.backend.status().get('max_linear', .03)), 'max_angular': min(4.5, self.backend.status().get('max_angular', .1)),
                    'watchdog_ms': int(self.grace_seconds * 1000), 'max_hold_seconds': None, 'server_time': time.time() * 1000}

class DemoBackend:
    """No ROS imports, serial ports, or motor writes."""
    def __init__(self):
        self.ready = False
        self.sent = []
    def status(self):
        return {'available': True, 'motor_ready': self.ready, 'other_publishers': 0, 'demo': True, 'max_linear': .9, 'max_angular': 4.5}
    def arm(self): self.ready = True
    def disarm(self): self.ready = False
    def publish(self, motion): self.sent.append(motion); self.sent = self.sent[-100:]; return motion
    def poll(self): pass
    def observation(self):
        return {'received_ns': time.monotonic_ns(), 'ros_stamp_ns': time.time_ns(), 'values': [0.,0.,0.,0.,0.,0.]}
    def close(self): pass
