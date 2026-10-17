"""Run with MYENGINE_SLICE_DLL pointing to the compiled DLL (or test .so)."""
import os,math,unittest
from types import SimpleNamespace as NS
from pathlib import Path
from engine_native4d import NativeSlicer
from engine_four_d import slice_layers
from engine_voxels import VoxelGrid
from engine_voxel_physics import boundary_mesh
from engine_assets import load_layers
from test_sections_voxel import triangle_volume

DLL=os.environ.get('MYENGINE_SLICE_DLL')
@unittest.skipUnless(DLL,'Set MYENGINE_SLICE_DLL to test the native 4D kernel')
class NativeTests(unittest.TestCase):
 def setUp(self):self.native=NativeSlicer(DLL)
 def tearDown(self):self.native.close()
 def assert_equivalent(self,layers,spacing,sw,angles,scale,cut):
  a=slice_layers(layers,spacing,sw,angles,scale,cut);b=self.native.slice(layers,spacing,sw,angles,scale,cut)
  self.assertEqual(a is None,b is None)
  if a is None:return
  for x,y in zip((*a.minimum,*a.maximum),(*b.minimum,*b.maximum)):self.assertAlmostEqual(x,y,places=5)
  self.assertAlmostEqual(triangle_volume(a),triangle_volume(b),places=4)
  self.assertTrue(all(math.isfinite(x) for x in b.vertices))
  for o in range(0,len(b.vertices),8):self.assertAlmostEqual(sum(x*x for x in b.vertices[o+3:o+6]),1,places=5)
 def test_closed_solid_hollow_negative_w_and_nonuniform_scale(self):
  solid=VoxelGrid((3,3,3),.6);hollow=solid.clone()
  for x in range(3):
   for y in range(3):
    for z in range(3):
     solid.set(x,y,z)
     if (x,y,z)!=(1,1,1):hollow.set(x,y,z)
  a=NS(geometry=boundary_mesh(solid));b=NS(geometry=boundary_mesh(hollow))
  for layers,angles,scale,sw,cut in [([a],(0,0,0),(1,1,1),1,0),([a,a],(45,0,0),(1,1,1),1,0),([b,a],(36,17,-8),(2,.5,1),1,.1),([a,b],(90,0,0),(1,1,1),-2,.2),([b],(12,-47,26),(-1,2,1),1,0),([a],(30,10,20),(1,1,1),1,20)]:
   with self.subTest(angles=angles,sw=sw):self.assert_equivalent(layers,.2,sw,angles,scale,cut)
 def test_real_spherecube(self):
  root=Path(__file__).resolve().parents[1];layers=[NS(geometry=m) for m in load_layers(root/'assets/spherecube.4d')]
  self.assert_equivalent(layers,.1,1,(20,15,0),(1,1,1),0)
 def test_invalid_parameters(self):
  g=VoxelGrid((1,1,1),1);g.set(0,0,0);layers=[NS(geometry=boundary_mesh(g))]
  with self.assertRaises(ValueError):self.native.slice(layers,.1,1,(0,0,0),(0,1,1),0)
  with self.assertRaises(ValueError):self.native.slice(layers,-.1,1,(0,0,0),(1,1,1),0)

if __name__=='__main__':unittest.main()
