import math,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from patrol import Grid,Limits,Planner

class BodyBlindCellTests(unittest.TestCase):
 def grid(self,value=-1,point=(0.,0.)):
  g=Grid(80,80,.05,(0,)*6400,-2.,-2.)
  data=list(g.data);data[g.cell(*point)]=value
  return Grid(g.width,g.height,g.resolution,tuple(data),g.origin_x,g.origin_y)
 def test_only_current_confirmed_body_unknown_is_handled(self):
  g=self.grid();lim=Limits(.22,known_body_radius=.10);p=Planner(g,(0.,0.,0.),(0.,0.),lim)
  self.assertIn(g.cell(0.,0.),p.safe)
  self.assertEqual(g.data[g.cell(0.,0.)],-1,'Raw SLAM map must stay unchanged')
 def test_obstacle_under_body_is_never_erased(self):
  g=self.grid(100);p=Planner(g,(0.,0.,0.),(0.,0.),Limits(.22,known_body_radius=.10))
  self.assertNotIn(g.cell(0.,0.),p.safe)
 def test_unknown_outside_body_still_blocks_start(self):
  g=self.grid(point=(.15,0.));p=Planner(g,(0.,0.,0.),(0.,0.),Limits(.22,known_body_radius=.10))
  self.assertNotIn(g.cell(0.,0.),p.safe)
 def test_default_never_assumes_body_geometry(self):
  g=self.grid();p=Planner(g,(0.,0.,0.),(0.,0.),Limits(.22))
  self.assertNotIn(g.cell(0.,0.),p.safe)
 def test_body_radius_cannot_be_expanded_to_conservative_envelope(self):
  for value in [.11,.22,-.1,math.nan,True]:
   with self.assertRaises(ValueError):Limits(.22,known_body_radius=value)

if __name__=='__main__':unittest.main()
