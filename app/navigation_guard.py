"""Opt-in Nav2 command guard. No ROS imports; clock/backend injectable for tests."""
import math
import time
from speed_limiter import slew_motion


class NavigationGuard:
    def __init__(self, backend, clock=time.monotonic, timeout=.3):
        self.backend, self.clock, self.timeout = backend,clock,timeout
        self.command = (0.,0.,0.); self.output = (0.,0.,0.)
        self.received = None; self.previous = clock(); self.armed = False; self.fault = None
        self.max_linear=.1;self.max_angular=.5

    def set_limits(self,linear,angular):
        if any(isinstance(v,bool) or not math.isfinite(v) for v in (linear,angular)) or not 0<linear<=.1 or not 0<angular<=.5:
            raise ValueError('자율주행 속도는 현재 검증 상한을 초과할 수 없습니다')
        self.max_linear,self.max_angular=linear,angular
        self.command=self.capped(self.command);self.output=self.capped(self.output)

    def capped(self,motion):
        x,y,yaw=motion
        ratio=min(1.,self.max_linear/math.hypot(x,y)) if x or y else 1.
        return x*ratio,y*ratio,max(-self.max_angular,min(self.max_angular,yaw))

    def receive(self, motion):
        if self.fault: return
        if len(motion) != 3 or not all(math.isfinite(value) for value in motion):
            self.stop('비정상 Nav2 속도 명령'); return
        self.command = self.capped(motion)
        self.received = self.clock()

    def stop(self, reason=None):
        self.fault = self.fault or reason
        self.command = self.output = (0.,0.,0.)
        try: self.backend.publish(self.output)
        except Exception: self.fault = '0 명령 발행 실패: 현장에서 정지를 확인하세요'
        if self.armed:
            try: self.backend.disarm()
            except Exception: self.fault = '모터 비활성화 확인 실패: 현장에서 정지를 확인하세요'
        self.armed = False

    def tick(self, sensors_ready=True):
        if self.fault: return
        now = self.clock(); state = self.backend.status()
        if state.get('other_publishers') or (self.armed and not state.get('available')):
            self.stop('다른 제어 프로그램 또는 ROS 연결 이상'); return
        if not sensors_ready:
            if self.armed: self.stop('LiDAR/odometry/TF 입력 중단')
            return
        if self.received is None: return
        if now-self.received > self.timeout:
            if self.armed: self.stop('Nav2 명령 수신 시간 초과')
            return
        if not any(self.command):
            self.stop(); self.previous = now; return
        if not self.armed:
            # Mark before arm: even an arm exception must attempt power-off.
            self.armed = True
            try: self.backend.arm()
            except Exception:
                self.stop('모터 활성화 실패'); return
            if self.clock()-self.received > self.timeout:
                self.stop('활성화 중 Nav2 명령 만료'); return
        state = self.backend.status()
        if not state.get('motor_ready') or not state.get('available') or state.get('other_publishers'):
            self.stop('모터 준비/제어권 확인 실패'); return
        target = self.backend.limit_motion(self.command)
        self.output = slew_motion(self.output,target,min(.05,max(0,now-self.previous)),linear_acceleration=.2,angular_acceleration=.4)
        try:
            applied = self.backend.publish(self.output)
            if applied is not None: self.output = tuple(applied)
        except Exception: self.stop('자율주행 명령 발행 실패')
        self.previous = now
