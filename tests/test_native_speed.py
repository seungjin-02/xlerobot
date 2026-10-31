import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'app'))
from native_speed import native_speed_policy, teleop_message

class NativeSpeedTests(unittest.TestCase):
    def setUp(self):
        self.status={'teleop': {'pads': {'drive': {'levels': [[.01,.06],[.23,1.53]],'max_level':1}, 'mapping':{'levels':[[.01,.06]],'max_level':0}}, 'limits':{'source':'base'}, 'is_allowed':True}}
    def test_uses_live_levels_and_distinguishes_pads(self):
        self.assertEqual(native_speed_policy(self.status)['levels'][-1],[.23,1.53])
        self.assertEqual(native_speed_policy(self.status,'mapping')['max_level'],0)
    def test_missing_policy_never_invents_fast_fallback(self):
        self.assertFalse(native_speed_policy({})['available'])
        with self.assertRaises(ValueError): teleop_message({},'drive',0,1,0,0)
    def test_stale_selection_rejected_after_limit_decreases(self):
        with self.assertRaises(ValueError): teleop_message(self.status,'mapping',1,1,0,0)
    def test_protocol_preserves_native_pad(self):
        self.assertEqual(teleop_message(self.status,'drive',1,1,0,0),dict(type='teleop',pad='drive',level=1,x=1,y=0,yaw=0))
    def test_corrupt_policy_and_nonfinite_axes_fail_closed(self):
        self.status['teleop']['pads']['drive']['levels'][0][0]=float('nan')
        self.assertFalse(native_speed_policy(self.status)['available'])
        with self.assertRaises(ValueError): teleop_message(self.status,'mapping',0,float('inf'),0,0)

if __name__=='__main__': unittest.main()
