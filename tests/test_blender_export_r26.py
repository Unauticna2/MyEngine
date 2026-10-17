"""Pure export-stream checks; this does not pretend to run Blender's UI or bpy."""
import importlib
import io
import math
from pathlib import Path
import sys
from types import ModuleType,SimpleNamespace as NS
import unittest
from engine_assets import parse_obj
root=Path(__file__).resolve().parents[1]
package=ModuleType('r26_addon_test');package.__path__=[str(root/'addons/myengine_4d')]
sys.modules[package.__name__]=package
exporter=importlib.import_module('r26_addon_test.exporter')

class Vec(list):
 @property
 def length_squared(self):return sum(v*v for v in self)
 def normalize(self):
  length=math.sqrt(self.length_squared)
  if length:self[:]=[v/length for v in self]
class Matrix:
 def __init__(self,flip=1,tx=0):self.flip,self.tx=flip,tx
 def to_3x3(self):return Matrix(self.flip)
 def determinant(self):return self.flip
 def inverted(self):return self
 def transposed(self):return self
 def __matmul__(self,v):return Vec([self.flip*v[0]+self.tx,v[1],v[2]])
def mesh():
 return NS(calc_loop_triangles=lambda:None,
  vertices=[NS(co=Vec(p),normal=Vec([0,0,1])) for p in [(0,0,0),(1,0,0),(0,1,0)]],
  loops=[NS(index=i,vertex_index=i) for i in range(3)],
  loop_triangles=[NS(loops=(0,1,2))],
  polygons=[NS(loop_indices=(0,1,2),use_smooth=True,normal=Vec([0,0,1]))],
  uv_layers=NS(active=NS(data=[NS(uv=uv) for uv in [(0,0),(1,0),(0,1)]])),
  corner_normals=[NS(vector=Vec([0,0,1])) for _ in range(3)])
class ExportTests(unittest.TestCase):
 def test_combined_siblings_keep_distinct_geometry_uv_and_normal_indices(self):
  out=io.StringIO();counts=[0,0,0]
  exporter.write_mesh(out,NS(name='A'),mesh(),Matrix(),counts)
  exporter.write_mesh(out,NS(name='B'),mesh(),Matrix(tx=10),counts)
  result=parse_obj(out.getvalue())
  self.assertEqual(len(result.vertices)//8,6);self.assertEqual(result.maximum,(11.,1.,0.))
  self.assertEqual(tuple(result.vertices[24:27]),(10.,0.,0.));self.assertIn('f 4/4/4 5/5/5 6/6/6',out.getvalue())
  self.assertEqual(list(result.vertices[6:8]),[0.,0.]);self.assertEqual(list(result.vertices[38:40]),[1.,0.])
 def test_negative_scale_keeps_outward_winding(self):
  out=io.StringIO();exporter.write_mesh(out,NS(name='Mirror'),mesh(),Matrix(-1),[0,0,0]);result=parse_obj(out.getvalue())
  a,b,c=[result.vertices[i:i+3] for i in (0,8,16)]
  cross_z=(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
  self.assertGreater(cross_z,0);self.assertEqual(result.vertices[5],1.)
 def test_nonfinite_coordinates_rejected(self):
  with self.assertRaises(ValueError):exporter.number(float('nan'))

 def exported_normals(self,source):
  out=io.StringIO();exporter.write_mesh(out,NS(name='Normals'),source,Matrix(),[0,0,0]);result=parse_obj(out.getvalue())
  return [tuple(result.vertices[i+3:i+6]) for i in range(0,len(result.vertices),8)]
 def test_missing_corner_normals_uses_calculated_legacy_loop_normals(self):
  source=mesh();del source.corner_normals;calls=[]
  def calculate():
   calls.append(True)
   for loop in source.loops:loop.normal=Vec([0,1,0])
  source.calc_normals_split=calculate
  self.assertEqual(self.exported_normals(source),[(0.,1.,0.)]*3)
  self.assertEqual(len(calls),1)
 def test_empty_corner_collection_uses_legacy_normals(self):
  source=mesh();source.corner_normals=[]
  def calculate():
   for loop in source.loops:loop.normal=Vec([1,0,0])
  source.calc_normals_split=calculate
  self.assertEqual(self.exported_normals(source),[(1.,0.,0.)]*3)
 def test_missing_normal_apis_preserves_flat_and_smooth_fallback(self):
  for smooth,expected in [(False,(0.,0.,1.)),(True,(1.,0.,0.))]:
   source=mesh();del source.corner_normals;source.polygons[0].use_smooth=smooth
   for v in source.vertices:v.normal=Vec([1,0,0])
   self.assertEqual(self.exported_normals(source),[expected]*3)
 def test_modern_loop_normals_keep_custom_values_without_legacy_api(self):
  source=mesh()
  for loop in source.loops:loop.normal=Vec([0,1,0])
  self.assertEqual(self.exported_normals(source),[(0.,1.,0.)]*3)
 def test_corner_property_is_never_accessed_even_if_it_raises(self):
  class ForbiddenCorner(NS):
   @property
   def corner_normals(self):raise AssertionError('corner_normals must never be accessed')
  source=ForbiddenCorner(**{k:v for k,v in vars(mesh()).items() if k!='corner_normals'})
  self.assertEqual(self.exported_normals(source),[(0.,0.,1.)]*3)
 def test_addon_entrypoint_reloads_a_stale_cached_exporter(self):
  from unittest.mock import patch
  bpy=ModuleType('bpy');props=ModuleType('bpy.props');extras=ModuleType('bpy_extras');io_utils=ModuleType('bpy_extras.io_utils')
  bpy.types=NS(Operator=type('Operator',(),{}),Panel=type('Panel',(),{}))
  for name in ('BoolProperty','EnumProperty','FloatProperty','StringProperty'):setattr(props,name,lambda **kw:None)
  io_utils.ExportHelper=type('ExportHelper',(),{});io_utils.ImportHelper=type('ImportHelper',(),{})
  source=root/'addons/myengine_4d/__init__.py'
  spec=importlib.util.spec_from_file_location('r26_addon_test',source,submodule_search_locations=[str(source.parent)])
  module=importlib.util.module_from_spec(spec)
  stale=lambda *args:None;exporter.export_hierarchy=stale
  with patch.dict(sys.modules,{'bpy':bpy,'bpy.props':props,'bpy_extras':extras,'bpy_extras.io_utils':io_utils,'r26_addon_test':module}):
   spec.loader.exec_module(module)
   self.assertEqual(module.ADDON_VERSION,'1.1.0')
   self.assertIsNot(module.export_hierarchy,stale)
   self.assertEqual(module.MYENGINE_PT_4d.bl_label,'MyEngine 4D 1.1.0')
 def test_zero_legacy_normals_fall_back_to_geometry(self):
  source=mesh();del source.corner_normals
  for loop in source.loops:loop.normal=Vec([0,0,0])
  self.assertEqual(self.exported_normals(source),[(0.,0.,1.)]*3)
 def test_zero_corner_normals_fall_back_to_geometry(self):
  source=mesh()
  for n in source.corner_normals:n.vector=Vec([0,0,0])
  self.assertEqual(self.exported_normals(source),[(0.,0.,1.)]*3)

if __name__=='__main__':unittest.main()
