import json,tempfile,unittest,struct
from pathlib import Path
from dataclasses import dataclass
from types import SimpleNamespace as NS
from unittest.mock import patch
from engine_runtime import Resources
from engine_resource_cache import ResourceCache
from engine_voxels import VoxelGrid
from engine_ui import SlideUI
from PNGJSONUnitylity import PNGJSONUnitylity as Save,encode_rgba,with_json,read_json,chunks,chunk,SIGNATURE

class Features25(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
 def tearDown(self):self.tmp.cleanup()
 def test_warm_mesh_shared_across_scene_lifetimes_and_invalidation(self):
  source=Path(__file__).resolve().parents[1]/'assets/Cube.obj';path=self.root/'cube.obj';path.write_bytes(source.read_bytes())
  ids=[];deleted=[];core=NS(create_mesh=lambda m:ids.append(len(ids)+1) or ids[-1],delete_mesh=deleted.append)
  a=Resources(core,self.root);a.preload(['cube.obj']*30,[]);layers=a.model('cube.obj');a.close()
  with patch('engine_runtime.load_layers',side_effect=AssertionError('warm cache decoded again')):
   b=Resources(core,self.root);b.preload(['cube.obj']*100,[]);self.assertIs(b.model('cube.obj'),layers);b.close()
  self.assertEqual(ids,[1]);self.assertEqual(deleted,[])
  path.write_text(path.read_text()+'\n# edited\n');c=Resources(core,self.root);self.assertIsNot(c.model('cube.obj'),layers);c.close();core.resource_cache.close();self.assertEqual(sorted(deleted),[1,2])
 def test_cache_budget_respects_live_leases(self):
  cache=ResourceCache(10);deleted=[]
  cache.get('a',lambda:1,lambda v:20,deleted.append);cache.trim();self.assertFalse(deleted)
  cache.release('a');self.assertEqual(deleted,[1]);cache.close()
 def test_voxels_copy_only_on_write(self):
  g=VoxelGrid((4,4,4),.2);g.set(1,1,1,(1,2,3,255));a=g.clone();b=g.clone()
  self.assertIs(a._storage,b._storage);a.set(1,1,1,(9,8,7,255))
  self.assertIsNot(a._storage,b._storage);self.assertEqual(b.get(1,1,1),(1,2,3,255));self.assertEqual(g.get(1,1,1),(1,2,3,255))
  with self.assertRaises(TypeError):b.pixels[0]=0
 def test_png_roundtrip_class_unicode_and_replacement(self):
  @dataclass
  class Data:position:list;food:int;name:str
  png=encode_rgba(2,1,bytes([255,0,0,255]*2));path=self.root/'save.png';value=Data([1,2,3],77,'Игрок')
  Save.ToPngJson(path,value,png);self.assertEqual(Save.FromPngJson(path,Data),value)
  original=dict(chunks(png));updated=with_json(path.read_bytes(),{'food':99});self.assertEqual(read_json(updated),{'food':99})
  self.assertEqual(sum(k==b'iTXt' for k,v in chunks(updated)),1);self.assertEqual(dict(chunks(updated))[b'IDAT'],original[b'IDAT'])
 def test_png_rejects_corruption_and_non_save(self):
  png=encode_rgba(1,1,b'\0\0\0\xff')
  for bad in (png,png[:-1],png[:-4]+b'0000'):
   with self.assertRaises(ValueError):read_json(bad)
  malformed=png[:-12]+chunk(b'iTXt',b'MyEngine.Save\0\0\0\0\0[]')+png[-12:]
  with self.assertRaises(ValueError):read_json(malformed)
  with self.assertRaises(ValueError):with_json(png,{'bad':float('nan')})
 def ui(self):
  d={'format':1,'kind':'MyEngine.UI','width':100,'height':100,'startSlide':'menu','slides':[
   {'id':'menu','elements':[{'id':'go','rect':[10,10,30,20],'onClick':[{'action':'next'}],'animations':[{'kind':'fade','duration':1}]}]},
   {'id':'hidden','enabled':False,'elements':[]}, {'id':'game','elements':[]} ]}
  path=self.root/'ui.json';path.write_text(json.dumps(d));self.scenes=[]
  self.world=NS(root=self.root,load_scene=self.scenes.append,scripts_allowed=True,find=lambda x:None)
  return SlideUI(self.world,'ui.json')
 def test_ui_hit_animated_letterbox_and_disabled_slide(self):
  ui=self.ui();self.assertIsNone(ui.hit(40,40,200,200));ui.update(.5);self.assertAlmostEqual(ui.pose(ui.slides['menu']['elements'][0])[-1],.5)
  ui.update(.1,(40,40,True,200,200));ui.update(.1,(40,40,False,200,200));self.assertEqual(ui.active,'game')
  ui.actions([{'action':'scene','path':'next.json'},{'action':'ui','enabled':False}]);self.assertEqual(self.scenes,['next.json']);self.assertFalse(ui.enabled)
  ui.set_slide_enabled('hidden',True);self.assertTrue(ui.show_slide('hidden'))
 def test_ui_does_not_fire_on_drag_out_or_disabled_element(self):
  ui=self.ui();ui.update(2);ui.update(.1,(20,20,True,100,100));ui.update(.1,(99,99,False,100,100));self.assertEqual(ui.active,'menu')
  ui.set_element_enabled('go',False);self.assertIsNone(ui.hit(20,20,100,100))
 def test_runtime_defaults_and_validation(self):
  from engine_runtime_options import normalized,native_flags
  opts=normalized();self.assertFalse(opts['diagnosticTitle']);self.assertEqual(native_flags(opts),9)
  self.assertEqual(native_flags(normalized({'mouseLook':False,'freeFly':False})),0)
  self.assertEqual(native_flags(opts,True),11)
  with self.assertRaises(ValueError):normalized({'scriptReload':1})

if __name__=='__main__':unittest.main()
