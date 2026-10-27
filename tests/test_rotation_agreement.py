import math,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from navigation_guard import rotation_disagreement

class RotationAgreementTests(unittest.TestCase):
 def test_map_offset_does_not_change_relative_rotation(self):
  self.assertAlmostEqual(rotation_disagreement(.3,0.,1.3,1.),0.)
 def test_mirrored_rotation_is_detected(self):
  self.assertGreater(rotation_disagreement(-.2,0.,.2,0.),.35)
 def test_wrap_at_pi_is_handled(self):
  self.assertAlmostEqual(rotation_disagreement(-math.pi+.1,math.pi-.1,.2,0.),0.)
 def test_invalid_feedback_rejected(self):
  with self.assertRaises(ValueError):rotation_disagreement(math.nan,0.,0.,0.)

if __name__=='__main__':unittest.main()
