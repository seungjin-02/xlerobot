import math
import unittest
from core import Controller, ControlError, DemoBackend
from speed_limiter import limit_motion

class Clock:
    def __init__(self): self.now = 100.
    def __call__(self): return self.now
    def advance(self, sec): self.now += sec

class ControlTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock(); self.backend=DemoBackend(); self.c=Controller(self.backend,self.clock)
        self.lease=self.c.arm('phone1'); self.seq=0
    def cmd(self,direction='forward',hold='selection1',speed=10/30):
        self.seq+=1; self.c.command('phone1',self.lease,self.seq,direction,speed,hold)
    def drive(self, seconds=1, direction='forward', hold='selection1', speed=10/30):
        for _ in range(round(seconds/.02)):
            self.cmd(direction,hold,speed);self.clock.advance(.02);self.c.tick()
    def test_requested_multipliers(self):
        for multiplier,expected in [(1,.03),(10,.3),(30,.9)]:
            self.cmd(speed=multiplier/30);self.assertAlmostEqual(self.c.motion[0],expected)
    def test_acceleration_is_bounded(self):
        self.cmd(speed=1);self.clock.advance(.02);self.c.tick()
        self.assertAlmostEqual(self.backend.sent[-1][0],.012)
        self.drive(2,speed=1);self.assertAlmostEqual(self.backend.sent[-1][0],.9)
    def test_rotation_maximum(self):
        self.drive(13,'turn_left',speed=1);self.assertAlmostEqual(self.c.motion[2],4.5);self.assertAlmostEqual(self.backend.sent[-1][2],4.5)
    def test_rotation_tracks_five_times_selected_linear_request(self):
        for multiplier, expected in [(1,.15),(10,1.5),(30,4.5)]:
            self.cmd('turn_left',speed=multiplier/30)
            self.assertAlmostEqual(self.c.motion[2],expected)
            self.cmd('turn_right',speed=multiplier/30)
            self.assertAlmostEqual(self.c.motion[2],-expected)
    def test_raw_request_preserved_separately_from_controller_cap(self):
        original=self.backend.status;self.backend.status=lambda:{**original(),'max_linear':.03}
        self.cmd(speed=10/30);self.assertAlmostEqual(self.c.desired_motion[0],.3);self.assertAlmostEqual(self.c.motion[0],.03)
    def test_final_published_motion_is_used_for_recording(self):
        original=self.backend.publish
        self.backend.publish=lambda motion:original(tuple(v*.5 for v in motion))
        self.drive(1)
        self.assertEqual(self.c.output_motion,self.backend.sent[-1])
    def test_live_robot_limit(self):
        original=self.backend.status;self.backend.status=lambda:{**original(),'max_linear':.03}
        self.drive();self.assertAlmostEqual(self.backend.sent[-1][0],.03)
    def test_toggle_off_immediately_stops(self):
        self.drive();self.cmd('idle',None)
        self.assertEqual(self.backend.sent[-1],(0.,0.,0.));self.assertEqual(self.c.output_motion,(0.,0.,0.))
    def test_latched_motion_has_no_three_second_limit(self):
        self.drive(20);self.assertTrue(self.backend.ready);self.assertGreater(self.backend.sent[-1][0],0)
        self.assertIsNone(self.c.status('phone1')['max_hold_seconds'])
    def test_direction_switch_has_no_zero_command(self):
        self.drive();self.backend.sent=[]
        self.cmd('left','selection2');self.clock.advance(.02);self.c.tick()
        output=self.backend.sent[-1];self.assertGreater(output[0],0);self.assertGreater(output[1],0)
        self.assertNotIn((0.,0.,0.),self.backend.sent)
        self.drive(1,'left','selection2');self.assertAlmostEqual(self.backend.sent[-1][0],0);self.assertAlmostEqual(self.backend.sent[-1][1],.3)
    def test_disconnect_continues_before_deadline(self):
        self.drive();previous=self.backend.sent[-1]
        for _ in range(499):self.clock.advance(.02);self.c.tick()
        self.assertTrue(self.backend.ready);self.assertEqual(previous,self.backend.sent[-1])
    def test_disconnect_does_not_accelerate(self):
        self.drive(.1,speed=1)
        for _ in range(31):self.clock.advance(.02);self.c.tick()
        frozen=self.backend.sent[-1]
        for _ in range(100):self.clock.advance(.02);self.c.tick()
        self.assertEqual(frozen,self.backend.sent[-1])
    def test_watchdog_disarms_after_ten_seconds(self):
        self.drive();self.clock.advance(10.01);self.c.tick()
        self.assertFalse(self.backend.ready);self.assertIsNone(self.c.lease);self.assertEqual(self.backend.sent[-1],(0.,0.,0.))
    def test_reconnect_before_deadline_same_lease(self):
        self.drive();old=self.c.lease;self.clock.advance(8)
        self.cmd('right','selection2');self.c.tick();self.assertEqual(self.c.lease,old)
        self.assertLess(self.c.motion[1],0)
    def test_toggle_off_while_disconnected_applied_on_reconnect(self):
        self.drive();self.clock.advance(5);self.cmd('idle',None)
        self.assertEqual(self.backend.sent[-1],(0.,0.,0.))
    def test_after_deadline_packet_cannot_resurrect(self):
        self.clock.advance(10.01)
        with self.assertRaises(ControlError):self.cmd()
        self.assertIsNone(self.c.lease)
    def test_duplicate_sequence_cannot_extend_grace(self):
        self.cmd();before=self.c.last_packet;self.clock.advance(1)
        with self.assertRaises(ControlError):self.c.command('phone1',self.lease,self.seq,'forward',1,'selection1')
        self.assertEqual(before,self.c.last_packet)
    def test_other_phone_cannot_drive_or_claim(self):
        with self.assertRaises(ControlError):self.c.command('phone2',self.lease,1,'forward',1,'x')
        with self.assertRaises(ControlError):self.c.arm('phone2')
    def test_old_selection_cannot_restart_after_toggle_off(self):
        self.cmd();self.cmd('idle',None);self.cmd();self.clock.advance(.02);self.c.tick()
        self.assertEqual(self.backend.sent[-1],(0.,0.,0.))
    def test_external_controller_stops_session(self):
        original=self.backend.status;self.backend.status=lambda:{**original(),'other_publishers':1}
        self.c.tick();self.assertFalse(self.backend.ready)
    def test_idle_timeout(self):
        for _ in range(160):
            if not self.c.lease:break
            self.cmd('idle',None);self.clock.advance(.1);self.c.tick()
        self.assertIsNone(self.c.lease)
    def test_invalid_speed_rejected(self):
        for speed in (float('nan'),float('inf'),1.1,-1,True):
            with self.assertRaises(ControlError):self.cmd(speed=speed)
    def test_cleanup_failure_invalidates_lease(self):
        self.backend.publish=lambda _:(_ for _ in ()).throw(RuntimeError('write failed'))
        self.c.stop(emergency=True);self.assertIsNone(self.c.lease);self.assertFalse(self.backend.ready);self.assertIsNotNone(self.c.cleanup_error)
    def test_old_lease_rejected_after_rearm(self):
        old=self.lease;self.c.stop(emergency=True);self.lease=self.c.arm('phone1')
        with self.assertRaises(ControlError):self.c.command('phone1',old,99,'forward',1,'old')
    def test_output_limit_applied_before_smoothing(self):
        p={'wheel_radius':.05,'base_radius':.125,'max_wheel_speed':18.25,'speed_tick_limit':3000,'speed_tick_scale':651.8986469044033}
        self.backend.limit_motion=lambda m:limit_motion(m,p)
        self.drive(2,speed=1)
        self.assertAlmostEqual(self.backend.sent[-1][0],limit_motion((.9,0,0),p)[0])
    def test_wheel_scaling_preserves_direction(self):
        p={'wheel_radius':.05,'base_radius':.125,'max_wheel_speed':18.25,'speed_tick_limit':3000,'speed_tick_scale':651.8986469044033}
        for requested in [(.9,0.,0.),(0.,.9,0.),(.3,.2,.1),(0.,0.,.1)]:
            output=limit_motion(requested,p);ratios=[b/a for a,b in zip(requested,output) if a]
            self.assertTrue(all(abs(r-ratios[0])<1e-10 for r in ratios))
            wheels=[(-math.sin(a)*output[0]-math.cos(a)*output[1]+.125*output[2])/.05 for a in (2*math.pi/3,0.,4*math.pi/3)]
            self.assertLessEqual(max(abs(w)*p['speed_tick_scale'] for w in wheels),3000.00001)

if __name__=='__main__':unittest.main(verbosity=2)
