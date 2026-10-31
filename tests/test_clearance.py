import math,random,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from clearance import euclidean_distances
from patrol import Grid,Limits,Planner

class ClearanceTests(unittest.TestCase):
 def test_matches_brute_force_over_random_rectangular_grids(self):
  rng=random.Random(42)
  for width,height in [(1,1),(1,8),(8,1),(4,9),(12,7)]:
   for _ in range(10):
    seeds=[rng.random()<.2 for _ in range(width*height)];seeds[rng.randrange(len(seeds))]=True
    actual=euclidean_distances(width,height,seeds)
    sources=[(i%width,i//width) for i,v in enumerate(seeds) if v]
    for i,d in enumerate(actual):self.assertAlmostEqual(d,min(math.hypot(i%width-x,i//width-y) for x,y in sources))
 def test_diagonal_clearance_is_euclidean(self):
  seeds=[False]*100;seeds[0]=True
  self.assertAlmostEqual(euclidean_distances(10,10,seeds)[43],5.)
 def test_diagonal_obstacle_outside_circle_does_not_block(self):
  g=Grid(40,40,.05,(0,)*1600,-1.,-1.);data=list(g.data);data[g.cell(.30,.30)]=100
  g=Grid(40,40,.05,tuple(data),-1.,-1.);p=Planner(g,(0.,0.,0.),(0.,0.),Limits(.22))
  self.assertIn(g.cell(0.,0.),p.safe)
 def test_obstacle_or_unknown_intersecting_margin_still_blocks(self):
  for value in [100,-1]:
   g=Grid(40,40,.05,(0,)*1600,-1.,-1.);data=list(g.data);data[g.cell(.20,.10)]=value
   g=Grid(40,40,.05,tuple(data),-1.,-1.);p=Planner(g,(0.,0.,0.),(0.,0.),Limits(.22))
   self.assertNotIn(g.cell(0.,0.),p.safe)
 def test_no_seeds_and_all_seeds(self):
  self.assertTrue(all(d>10 for d in euclidean_distances(10,10,[False]*100)))
  self.assertEqual(euclidean_distances(10,10,[True]*100),[0.]*100)

if __name__=='__main__':unittest.main()
