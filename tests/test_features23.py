import ast,json,tempfile,time,unittest,threading
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace as NS
from engine_blueprints import example,generated_source,Graph
from engine_build import build_scene,prepare_build_scenes,copy_project,validate_project
from engine_projects import create_project
from engine_scene import atomic_json,SceneDocument
from engine_packages import prepare_package,package_files,repo_name,valid_repo,search_page,publish_new
from engine_skybox import sky_settings,sky_paths
from engine_slice_jobs import SliceJobs
ROOT=Path(__file__).resolve().parent.parent

class BlueprintTests(unittest.TestCase):
 def test_execute_rotation_and_preserve_user_code(self):
  source,unused=generated_source(example());self.assertEqual(unused,[]);ns={};exec(source,ns)
  values=[];s=ns['Script']();s.entity=NS(rotate=lambda *x:values.append(x));s.update(.5)
  self.assertEqual(values,[(0,15.,0)])
  old='# user header\n'+source+'\nCUSTOM=42\n';d=example();d['nodes'][2]['params']['a']=60
  new,_=generated_source(d,old);ast.parse(new);self.assertTrue(new.startswith('# user header\n'));self.assertTrue(new.endswith('CUSTOM=42\n'))
 def test_branch_and_escaped_literals(self):
  d={'format':1,'nodes':[{'id':'1','type':'Update'},{'id':'2','type':'KeyDown'},{'id':'3','type':'Branch'},{'id':'4','type':'Spawn','params':{'model':"odd'path.obj",'script':'test.py'}},{'id':'5','type':'Print','params':{'text':'idle'}}], 'links':[['1','next','3','in'],['2','value','3','condition'],['3','true','4','in'],['3','false','5','in']]}
  ns={};exec(generated_source(d)[0],ns);s=ns['Script']();events=[]
  s.world=NS(input=NS(down=lambda k:True),instantiate=lambda *a,**kw:events.append((a,kw)),log=events.append);s.update(.1)
  self.assertEqual(events[0][0],("odd'path.obj",));self.assertEqual(events[0][1]['scripts'],['test.py'])
  s.world.input.down=lambda k:False;s.update(.1);self.assertEqual(events[-1],'idle')
 def test_reject_cycles_types_and_unknown_regions(self):
  for link in (['2','value','4','in'],['3','value','3','a']):
   d=example();d['links'].append(link)
   with self.assertRaises(ValueError):Graph(d)
  with self.assertRaises(ValueError):generated_source(example(),'MY_WORK=1\n')
 def test_impulse_api(self):
  d={'format':1,'nodes':[{'id':'1','type':'Start'},{'id':'2','type':'Impulse'}],'links':[['1','next','2','in']]};ns={};exec(generated_source(d)[0],ns)
  events=[];s=ns['Script']();s.entity=NS(rigidbody=NS(add_force=lambda *a,**kw:events.append((a,kw))));s.start()
  self.assertEqual(events,[(((0,5,0),),{'mode':'impulse'})])

class BuildFlagTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name);self.root=create_project(ROOT,self.base,'Game');self.scene=self.root/'scenes/main.json'
 def tearDown(self):self.tmp.cleanup()
 def test_remove_model_keep_physics_and_source(self):
  d=SceneDocument.load(self.scene).data;d['model'][0]='assets/editor.obj';(self.root/'assets/editor.obj').write_bytes((ROOT/'assets/Cube.obj').read_bytes())
  d['omitModelInBuild'][0]=True;d['colliders'][0]={'type':'box'};d['editorOnly'][1]=True;atomic_json(self.scene,d);original=self.scene.read_bytes()
  out=self.base/'out';copy_project(self.root,out,lambda x:None);prepare_build_scenes(self.root,out);built=json.loads((out/'scenes/main.json').read_text())
  self.assertEqual(len(built['model']),1);self.assertIsNone(built['model'][0]);self.assertFalse(built['visible'][0]);self.assertEqual(len(built['colliders'][0]['size']),3)
  self.assertFalse((out/'assets/editor.obj').exists());self.assertEqual(original,self.scene.read_bytes())
 def test_shared_asset_kept(self):
  d=SceneDocument.load(self.scene).data;d['omitModelInBuild'][0]=True;atomic_json(self.scene,d)
  out=self.base/'out';copy_project(self.root,out,lambda x:None);prepare_build_scenes(self.root,out);self.assertTrue((out/'assets/Cube.obj').exists())
 def test_mesh_kept_for_collision(self):
  d={'model':['assets/Cube.obj'],'positions':[{}],'colors':[{}],'colliders':[{'type':'mesh'}],'omitModelInBuild':[True]}
  out=build_scene(d);self.assertEqual(out['model'],['assets/Cube.obj']);self.assertEqual(out['visible'],[False])
 def test_excluded_missing_asset_and_sky_validation(self):
  d=SceneDocument.load(self.scene).data;d['model'][1]='missing.obj';d['editorOnly'][1]=True;atomic_json(self.scene,d);validate_project(self.root,'scenes/main.json')
  d['skybox']={'texture':'missing.png'};atomic_json(self.scene,d)
  with self.assertRaises(FileNotFoundError):validate_project(self.root,'scenes/main.json')

class PackageTests(unittest.TestCase):
 def test_staging_manifest_no_credentials(self):
  with tempfile.TemporaryDirectory() as td:
   base=Path(td);root=create_project(ROOT,base,'Demo');(root/'.env').write_text('secret');(root/'credentials.json').write_text('secret')
   names=dict(package_files(root));self.assertNotIn('.env',names);self.assertNotIn('credentials.json',names)
   result=prepare_package(root,base/'stage','Demo','scenes/main.json','Описание <html>',ROOT/'textures/checker.png')
   stage=Path(result['path']);self.assertTrue((stage/'package.zip').is_file());self.assertIn('&lt;html&gt;',(stage/'index.html').read_text())
   self.assertEqual(json.loads((stage/'package.json').read_text())['name'],'MyPackege_Demo');self.assertEqual((stage/'Data.txt').read_text(),'Описание <html>')
   with self.assertRaises(FileExistsError):prepare_package(root,stage,'Demo','scenes/main.json','',ROOT/'textures/checker.png')
 def test_names_and_search_pagination(self):
  self.assertEqual(repo_name('Test'),'MyPackege_Test')
  for name in ('../../oops','a/b','!bad'):
   with self.assertRaises(ValueError):repo_name(name)
  raw={'total_count':150,'incomplete_results':False,'items':[{'name':'MyPakege_Test','full_name':'author/MyPakege_Test','default_branch':'main','topics':[]}]}
  with patch('engine_packages.http_bytes',return_value=json.dumps(raw).encode()):
   r=search_page();self.assertEqual(len(r['items']),1);self.assertTrue(r['more'])
 def test_publication_commands_mocked_no_remote_writes(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td);atomic_json(p/'package.json',{'name':'MyPackege_Test'});calls=[]
   def fake(args,*a,**kw):calls.append((args,kw));return 'author' if args[1:]==['api','user','--jq','.login'] else ''
   with patch('engine_packages.executable',side_effect=lambda n:n),patch('engine_packages.run',side_effect=fake):r=publish_new(p)
   self.assertEqual(r['pages'],'https://author.github.io/MyPackege_Test/')
   pages=[kw for a,kw in calls if 'repos/author/MyPackege_Test/pages' in a]
   self.assertEqual(json.loads(pages[0]['input_text'])['source']['branch'],'main')
   self.assertTrue(any(a[1:3]==['repo','create'] and '--public' in a for a,kw in calls))

class JobTests(unittest.TestCase):
 def test_background_queue_latest_request_and_no_wait(self):
  gate=threading.Event();calls=[];layers=[NS(geometry=object())]
  def compute(*args):calls.append(args[-1]);gate.wait(2);return None
  with patch('engine_slice_jobs.slice_layers',side_effect=compute):
   jobs=SliceJobs();key=(0,.1,1,(20,0,0),(1,1,1))
   try:
    start=time.perf_counter();self.assertIsNone(jobs.get(1,layers,key,None));self.assertLess(time.perf_counter()-start,.1)
    for i in range(1,50):jobs.get(1,layers,(i,*key[1:]),None)
    self.assertLessEqual(len(jobs.pending),1);gate.set();got=[];deadline=time.monotonic()+2
    while time.monotonic()<deadline:
     result=jobs.get(1,layers,(49,*key[1:]),None)
     if result:got.append(result[0][0])
     if 49 in got:break
     time.sleep(.005)
    self.assertIn(49,got);self.assertLessEqual(len(calls),3)
   finally:gate.set();jobs.close()

class SkyTests(unittest.TestCase):
 def test_settings(self):
  self.assertEqual(sky_paths(ROOT,'assets/skybox/skymask2.png'),['assets/skybox/skymask2.png'])
  with self.assertRaises(ValueError):sky_settings(ROOT,{'faces':{'px':'x.png'}})
  with self.assertRaises(ValueError):sky_settings(ROOT,{'texture':'x.png','exposure':float('nan')})

if __name__=='__main__':unittest.main()
