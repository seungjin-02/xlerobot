import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from map_library import MapLibrary
class MapLibraryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.maps=self.root/'maps';self.maps.mkdir();self.lib=MapLibrary(self.maps,self.root/'meta/library.json');(self.maps/'room.yaml').write_text('image: room.pgm\nresolution: 0.05\norigin: [0,0,0]\n');(self.maps/'room.pgm').write_bytes(b'P5\n1 1\n255\n\xff')
 def tearDown(self):self.tmp.cleanup()
 def test_routes_survive_new_instance_without_modifying_original_map(self):
  before=(self.maps/'room.yaml').read_bytes();self.lib.save('room.yaml','실험실',[dict(x=1,y=2,yaw=0)])
  self.assertEqual(MapLibrary(self.maps,self.lib.metadata).read()['maps']['room.yaml']['label'],'실험실');self.assertEqual(before,(self.maps/'room.yaml').read_bytes())
 def test_export_contains_relative_image_and_route(self):
  self.lib.save('room.yaml','room',[])
  with zipfile.ZipFile(io.BytesIO(self.lib.export('room.yaml'))) as z:
   self.assertEqual(set(z.namelist()),{'room.yaml','room.pgm','mobile-route.json'})
 def test_path_traversal_rejected(self):
  for name in ('../room.yaml','/room.yaml','.room.yaml','a\\room.yaml'):
   with self.assertRaises(ValueError):self.lib.resolve(name)
 def test_nonfinite_waypoint_never_written(self):
  with self.assertRaises(ValueError):self.lib.save('room.yaml','room',[dict(x=float('nan'),y=0,yaw=0)])
  self.assertFalse(self.lib.metadata.exists())
 def test_external_image_rejected(self):
  (self.root/'outside.pgm').write_bytes(b'no');(self.maps/'room.yaml').write_text('image: ../outside.pgm')
  with self.assertRaises(ValueError):self.lib.export('room.yaml')
 def test_external_map_symlink_rejected(self):
  p=self.maps/'link.yaml'
  try:p.symlink_to(self.root/'private.yaml')
  except OSError:self.skipTest('No symlink support')
  (self.root/'private.yaml').write_text('image: room.pgm')
  with self.assertRaises(ValueError):self.lib.resolve('link.yaml')
if __name__=='__main__':unittest.main()
