import importlib.util
import io
import json
import math
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
from array import array
from engine_assets import load_layers,parse_obj,four_d_spacing
from engine_liquid import State,Native,python_step,simulate,mesh_from_state,LiquidSystem,settings as fluid_settings
from engine_releases import load_settings,save_settings,bump_version,BuildVersionLock
from engine_platform_build import export_target,PublicationError
ROOT=Path(__file__).resolve().parents[1]
NATIVE=ROOT/'platforms/linux/libFluidNative.so'
spec=importlib.util.spec_from_file_location('hierarchy_helper',ROOT/'addons/myengine_4d/hierarchy.py')
hierarchy=importlib.util.module_from_spec(spec);spec.loader.exec_module(hierarchy)
TRI='v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n'

class VersionTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
 def tearDown(self):self.tmp.cleanup()
 def test_increment_numeric_and_manual_versions(self):
  for a,b in [('0.1.0','0.1.1'),('1.9.99','1.9.100'),('42','43')]:self.assertEqual(bump_version(a),b)
  for bad in ('v1.0','1.0-beta','1..2','-1','1.'): 
   with self.assertRaises(ValueError):bump_version(bad)
  save_settings(self.root,{'version':'beta','autoIncrementVersion':False})
  with patch('engine_platform_build.export_game',return_value=self.root):export_target('Windows x64',self.root,self.root)
  self.assertEqual(load_settings(self.root)['version'],'beta')
 def test_two_successes_and_failure_between(self):
  with patch('engine_platform_build.export_game',return_value=self.root) as build:
   export_target('Windows x64',self.root,self.root)
   self.assertEqual(build.call_args.kwargs['release_options']['version'],'0.1.1')
  self.assertEqual(load_settings(self.root)['version'],'0.1.1')
  with patch('engine_platform_build.export_game',side_effect=RuntimeError('compiler failed')):
   with self.assertRaises(RuntimeError):export_target('Windows x64',self.root,self.root)
  self.assertEqual(load_settings(self.root)['version'],'0.1.1')
  with patch('engine_platform_build.export_game',return_value=self.root):export_target('Windows x64',self.root,self.root)
  self.assertEqual(load_settings(self.root)['version'],'0.1.2')
 def test_upload_failure_commits_exactly_once(self):
  save_settings(self.root,{'version':'2.4.8','publishAfterBuild':True,'repository':'author/game'})
  with patch('engine_platform_build.export_game',return_value=self.root),patch('engine_releases.publish_build',side_effect=RuntimeError('offline')) as upload:
   with self.assertRaises(PublicationError) as caught:export_target('Windows x64',self.root,self.root)
   self.assertTrue(caught.exception.retry_publication);self.assertEqual(caught.exception.build,self.root)
   self.assertEqual(upload.call_args.args[1]['version'],'2.4.9')
  self.assertEqual(load_settings(self.root)['version'],'2.4.9')
 def test_stale_window_cannot_overwrite_new_version(self):
  save_settings(self.root,{'version':'3.0.2'})
  with patch('engine_platform_build.export_game') as build:
   with self.assertRaisesRegex(RuntimeError,'другом окне'):export_target('Windows x64',self.root,self.root,expected_version='3.0.1',release_options={'version':'3.0.1'})
   build.assert_not_called()
  self.assertEqual(load_settings(self.root)['version'],'3.0.2')
 def test_lock_released_on_failure_and_rejects_parallel_build(self):
  with BuildVersionLock(self.root):
   with self.assertRaises(RuntimeError):
    with BuildVersionLock(self.root):pass
  with BuildVersionLock(self.root):pass
 def test_settings_failure_reports_existing_build(self):
  with patch('engine_platform_build.export_game',return_value=self.root),patch('engine_releases.save_settings',side_effect=OSError('read only')),patch('engine_releases.publish_build') as publish:
   with self.assertRaises(PublicationError) as caught:export_target('Windows x64',self.root,self.root)
   self.assertFalse(caught.exception.retry_publication);publish.assert_not_called()

class FluidTests(unittest.TestCase):
 def test_settings_reject_invalid_inputs(self):
  for value in ({'nx':0},{'depth':float('nan')},{'solid':[False]},{'updateHz':0},{'cellSize':0}):
   with self.assertRaises(ValueError):fluid_settings(value)
 def test_still_water_and_upward_faces(self):
  s=State({'nx':4,'nz':3});before=list(s.h)
  for _ in range(100):python_step(s,.01)
  self.assertEqual(list(s.h),before);mesh=mesh_from_state(s)
  a,b,c=(mesh.vertices[i:i+3] for i in (0,8,16))
  self.assertGreater((b[2]-a[2])*(c[0]-a[0])-(b[0]-a[0])*(c[2]-a[2]),0)
  self.assertTrue(all(abs(mesh.vertices[i]-1)<1e-6 for i in range(4,len(mesh.vertices),8)))
 def test_add_water_splash_preserve_volume_nonnegative(self):
  s=State({'nx':10,'nz':8,'depth':.1});initial=s.volume()
  s.command('water',0,0,.2,.7);self.assertAlmostEqual(s.volume(),initial+.2)
  s.command('splash',0,0,7,1);before=list(s.h)
  for _ in range(500):python_step(s,.01)
  self.assertNotEqual(before,list(s.h));self.assertAlmostEqual(s.volume(),initial+.2,places=10)
  self.assertGreaterEqual(min(s.h),0);self.assertTrue(all(math.isfinite(v) for v in s.h))
 def test_solid_barrier_blocks_flow(self):
  solid=[x==3 for z in range(5) for x in range(7)]
  s=State({'nx':7,'nz':5,'depth':0,'solid':solid});s.command('water',-.6,0,.2,.3)
  for _ in range(200):python_step(s,.005)
  self.assertEqual(sum(s.h[z*7+x] for z in range(5) for x in range(3,7)),0)
  self.assertAlmostEqual(s.volume(),.2)
 def test_dry_step_blocks_old_momentum(self):
  s=State({'nx':2,'nz':2,'depth':0,'bed':[0,5,0,5]});s.h[0]=1;s.qx[0]=1
  python_step(s,.01);self.assertEqual(s.qx[0],0);self.assertEqual(s.h[1],0)
 @unittest.skipUnless(NATIVE.exists(),'Build FluidNative.cpp first')
 def test_native_matches_reference_and_conserves(self):
  step=Native(NATIVE);a=State({'nx':8,'nz':6,'depth':.3});b=State(a.config)
  for s in (a,b):s.command('water',-.4,.2,.5,.5);s.command('splash',.3,0,3,.8)
  volume=a.volume()
  for _ in range(300):step(a,.01);python_step(b,.01)
  self.assertLess(max(abs(x-y) for x,y in zip(a.h,b.h)),1e-10);self.assertAlmostEqual(a.volume(),volume,places=10)
  self.assertGreaterEqual(min(a.h),0)
 @unittest.skipUnless(NATIVE.exists(),'Build FluidNative.cpp first')
 def test_async_jobs_apply_graphics_on_owner_and_remove_safely(self):
  owner=threading.get_ident();graphics=[];counter=[0]
  def create(mesh):
   self.assertEqual(threading.get_ident(),owner);counter[0]+=1;graphics.append(('new',counter[0]));return counter[0]
  def delete(handle):self.assertEqual(threading.get_ident(),owner);graphics.append(('delete',handle))
  world=NS(core=NS(create_mesh=create,delete_mesh=delete),physics=NS(geometry={}),resources=NS(model=lambda _:[]),log=Mock())
  class Entity:
   is_4d=False;voxels=None;rigidbody=None;collider=None;destroyed=False;active=True;model=None
   def __init__(self,uid):self.uid=uid;self.name=str(uid)
   def _check(self):assert threading.get_ident()==owner
   def sync(self):self._check()
  system=LiquidSystem(world);system.step=Native(NATIVE);a,b=Entity(1),Entity(2)
  try:
   ca=system.add(a,{'nx':6,'nz':6});cb=system.add(b,{'nx':6,'nz':6});initial=ca.volume
   ca.add_water(volume=.1);cb.splash();system.tick(.05)
   ca.future.result(timeout=10);cb.future.result(timeout=10);system.tick(0)
   self.assertAlmostEqual(ca.volume,initial+.1);self.assertTrue(any(k=='delete' for k,_ in graphics))
   ca.splash();system.tick(.05);system.remove(a);self.assertIsNone(a.liquid)
  finally:system.close()
  self.assertEqual(len([v for k,v in graphics if k=='new']),len([v for k,v in graphics if k=='delete']))
 def test_scene_and_prefab_data_keep_component(self):
  from engine_scene import SceneDocument
  from engine_build import build_scene
  doc=SceneDocument({'model':[None],'liquids':[{'nx':8,'nz':8}]})
  self.assertEqual(build_scene(doc.data)['liquids'][0]['nx'],8)
  with self.assertRaises(ValueError):SceneDocument({'model':['bad.4d'],'liquids':[{}]})

class HierarchyTests(unittest.TestCase):
 def node(self,name,kind='MESH',children=()):return NS(name=name,type=kind,children=list(children))
 def test_siblings_share_layer_and_nested_children_advance(self):
  b=self.node('B');c=self.node('C');a=self.node('A',children=[b,c]);root=self.node('Root',children=[a])
  groups=hierarchy.group_layers(root)
  self.assertEqual([[o.name for o in g] for g in groups],[['Root'],['A'],['B','C']])
 def test_root_empty_container_and_empty_intermediate_keep_spacing(self):
  root=self.node('Root','EMPTY',[self.node('A',children=[self.node('Gap','EMPTY',[self.node('B')])])])
  self.assertEqual([[o.name for o in g] for g in hierarchy.group_layers(root)],[['A'],['Gap'],['B']])
  self.assertEqual(len(hierarchy.group_layers(root,'ROOT')),4)
 def test_depth_limit_and_cycle(self):
  root=self.node('Root');root.children=[root]
  with self.assertRaises(ValueError):hierarchy.group_layers(root)
  for _ in range(256):root=self.node('N',children=[root if _ else self.node('Leaf')])
  with self.assertRaises(ValueError):hierarchy.group_layers(root)
 def test_roundtrip_header_empty_layers_and_native_slicing(self):
  from engine_native4d import NativeSlicer
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'hierarchy.4d';hierarchy.atomic_export(p,lambda out:out.write(hierarchy.header(.25,'ROOT')+TRI+'+\n# myengine_empty_layer\n+\n'+TRI))
   layers=load_layers(p);self.assertEqual(len(layers),3);self.assertFalse(layers[1].vertices);self.assertEqual(four_d_spacing(p),.25)
   self.assertEqual(layers[0].layer_spacing,.25)
   dll=ROOT/'platforms/linux/libSlice4D.so'
   if dll.exists():
    native=NativeSlicer(dll)
    try:
     items=[NS(geometry=x) for x in layers]
     self.assertIsNotNone(native.slice(items,.25,1,(0,0,0),(1,1,1),0))
     self.assertIsNone(native.slice(items,.25,1,(0,0,0),(1,1,1),.25))
     self.assertIsNotNone(native.slice(items,.25,1,(0,0,0),(1,1,1),.5))
    finally:native.close()
 def test_failed_export_preserves_existing_file(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'object.4d';p.write_text('previous')
   def fail(out):out.write('partial');raise ValueError('invalid mesh')
   with self.assertRaises(ValueError):hierarchy.atomic_export(p,fail)
   self.assertEqual(p.read_text(),'previous');self.assertEqual(list(Path(d).iterdir()),[p])
 def test_empty_marker_cannot_hide_geometry(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'object.4d';p.write_text('# myengine_empty_layer\n'+TRI)
   with self.assertRaises(ValueError):load_layers(p)

if __name__=='__main__':unittest.main()
