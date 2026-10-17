import copy,json,os,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from engine_scene import SceneDocument
from engine_scriptable import ScriptableObject
from engine_prefabs import save_prefab,load_prefab,append_prefab
from engine_trust import allowed,set_allowed
from engine_runtime import ScriptBinding
from engine_theme import effective
from engine_node_api import load_plugins,DEFINITIONS
from engine_blueprints import SPECS,generated_source
from engine_build_options import normalized,excluded
from engine_build import copy_project,prepare_build_scenes,validate_project

class Features24(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
 def tearDown(self):
  for k in tuple(DEFINITIONS):SPECS.pop(k,None)
  DEFINITIONS.clear();self.tmp.cleanup()
 def test_themes(self):
  self.assertEqual([effective('Automatic',h) for h in (6,7,19,20)],['Dark','Light','Light','Dark'])
  self.assertEqual(effective('Sunlight',23),'Sunlight')
 def test_scriptable_schema_roundtrip_and_independent_clones(self):
  s=ScriptableObject({'health':100,'offset':[0,1,0]},type_name='Stats',schema={'health':{'type':'float','min':0,'max':100},'offset':{'type':'vec3'},'speed':{'type':'float','default':4}})
  path=self.root/'stats.scriptable.json';s.save(path);restored=ScriptableObject.load(path);c=restored.clone();c['health']=25
  self.assertEqual(restored['health'],100);self.assertEqual(c['speed'],4)
  v=c['offset'];v[0]=9;self.assertEqual(c['offset'],[0,1,0])
  with self.assertRaises(ValueError):c['health']=-1
  with self.assertRaises(ValueError):c['offset']=[0,float('nan'),0]
  self.assertEqual(c['health'],25)
 def test_prefab_relative_position_trust_custom_fields_and_undo(self):
  d=SceneDocument({'model':[None,None],'names':['A','B'],'positions':[{'x':10,'y':2,'w':.2},{'x':12,'y':3,'w':.3}],'scriptTrusted':[False,True],'custom':['red','blue']})
  path=self.root/'pair.prefab.json';save_prefab(path,d,[0,1]);p=load_prefab(path)
  self.assertEqual(p['positions'][0],dict(x=0,y=0,z=0,w=0));self.assertAlmostEqual(p['positions'][1]['w'],.1)
  before=copy.deepcopy(d.data);ids=append_prefab(d,p,(20,0,0));self.assertEqual(ids,[2,3]);self.assertEqual(d.data['positions'][3]['x'],22)
  self.assertEqual(d.data['scriptTrusted'][2:], [False,True]);self.assertEqual(d.data['custom'][2:],['red','blue'])
  self.assertEqual(d.data['names'][2:],['A 1','B 1']);d.undo();self.assertEqual(d.data,before)
 def test_script_trust_blocks_top_level_before_import(self):
  p=self.root/'blocked.py';flag=self.root/'executed.txt'
  p.write_text('from pathlib import Path\nPath('+repr(str(flag))+').write_text("yes")\nclass Script: pass\n')
  self.assertTrue(allowed(self.root));set_allowed(self.root,False);self.assertFalse(allowed(self.root))
  world=NS(scripts_allowed=False);e=NS(id=1,world=world,script_trusted=True,name='x');binding=ScriptBinding(e,p)
  self.assertTrue(binding.reload());self.assertFalse(flag.exists());self.assertIsNone(binding.instance)
  world.scripts_allowed=True;e.script_trusted=False;self.assertTrue(binding.reload());self.assertFalse(flag.exists())
  e.script_trusted=True;self.assertTrue(binding.reload(defer_start=True));self.assertTrue(flag.exists())
  import sys;sys.modules.pop(binding.module_name,None)
 def test_developer_nodes_compile_execute_rollback_and_trust(self):
  folder=self.root/'plugins/nodes';folder.mkdir(parents=True);p=folder/'custom.py'
  p.write_text('''def register(api):
 api.define('TestDouble', params={'x':2}, inputs={'x':'number'}, outputs={'value':'number'}, expression=lambda c: '('+c.input('x')+')*2')
 api.define('TestLog', params={'x':0}, inputs={'in':'exec','x':'number'}, outputs={'next':'exec'}, action=lambda c: 'self.world.log('+c.input('x')+')')
''')
  self.assertEqual(load_plugins(self.root),['TestDouble','TestLog'])
  graph={'format':1,'nodes':[{'id':'1','type':'Start'},{'id':'2','type':'TestDouble','params':{'x':7}},{'id':'3','type':'TestLog'}],'links':[['1','next','3','in'],['2','value','3','x']]}
  text,unused=generated_source(graph);scope={};exec(text,scope);values=[];scope['_bp_start'](NS(world=NS(log=values.append)));self.assertEqual(values,[14]);self.assertEqual(unused,[])
  p.write_text('raise RuntimeError("bad plugin")')
  with self.assertRaises(RuntimeError):load_plugins(self.root)
  self.assertIn('TestDouble',SPECS);self.assertIn('TestDouble',DEFINITIONS)
  set_allowed(self.root,False)
  with self.assertRaises(PermissionError):load_plugins(self.root)
  with self.assertRaises(PermissionError):generated_source(graph)
 def test_build_excludes_sources_and_library_but_keeps_prefab_dependencies(self):
  root=self.root/'project';root.mkdir();(root/'assets').mkdir();(root/'native').mkdir();(root/'scripts').mkdir()
  engine=Path(__file__).resolve().parents[1]
  (root/'assets/Cube.obj').write_bytes((engine/'assets/Cube.obj').read_bytes())
  SceneDocument({'model':['assets/Cube.obj'],'omitModelInBuild':[True]}).save(root/'main.json')
  doc=SceneDocument({'model':['assets/Cube.obj'],'scripts':[['scripts/a.py']]});save_prefab(root/'assets/item.prefab.json',doc,[0])
  for name in ('a.c','a.cs','a.cpp','a.asm','a.dll','keep.dll'):(root/'native'/name).write_text('fixture')
  (root/'scripts/a.py').write_text('# fixture');out=self.root/'Data';out.mkdir()
  copy_project(root,out,lambda x:None,normalized(files=['native/a.dll']));prepare_build_scenes(root,out);validate_project(out,'main.json')
  self.assertEqual(sorted(p.name for p in (out/'native').iterdir()),['keep.dll']);self.assertTrue((out/'assets/Cube.obj').is_file())
  (out/'scripts/a.py').unlink()
  with self.assertRaises(FileNotFoundError):validate_project(out,'main.json')
  self.assertTrue(excluded('Native/a.CPP',normalized()));self.assertFalse(excluded('a.cpp',normalized([])))
 def test_prefab_build_flags_and_explicit_exclusion(self):
  root=self.root/'project';root.mkdir();SceneDocument({'model':[]}).save(root/'main.json')
  doc=SceneDocument({'model':[None,None],'names':['Only editor','Runtime'],'editorOnly':[True,False]});save_prefab(root/'item.prefab.json',doc,[0,1])
  out=self.root/'Data';out.mkdir();copy_project(root,out,lambda x:None);prepare_build_scenes(root,out)
  self.assertEqual(load_prefab(out/'item.prefab.json')['names'],['Runtime'])
  out2=self.root/'Data2';out2.mkdir();copy_project(root,out2,lambda x:None,normalized(files=['item.prefab.json']));prepare_build_scenes(root,out2)
  self.assertFalse((out2/'item.prefab.json').exists())

if __name__=='__main__':unittest.main()
