import json,math,stat,sys,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine_assets import parse_obj
from engine_access import set_unlock_all,unlock_all
from engine_transactions import Transactions
from engine_releases import make_metadata,publish_build,extract_archive,restore_release,settings
from engine_platform_build import export_target,PublicationError
G='v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\n'
def normals(mesh):return [tuple(mesh.vertices[i+3:i+6]) for i in range(0,len(mesh.vertices),8)]
class SmoothingTests(unittest.TestCase):
 def test_off_keeps_hard_edge(self):
  ns=normals(parse_obj(G+'s off\nf 1 2 3\nf 1 4 2\n'));self.assertEqual(ns[0],(0.,0.,1.));self.assertEqual(ns[3],(0.,1.,0.))
 def test_on_blends_shared_vertices(self):
  ns=normals(parse_obj(G+'s on\nf 1 2 3\nf 1 4 2\n'))
  for i in (0,1,3,5):self.assertAlmostEqual(ns[i][1],math.sqrt(.5),places=6);self.assertAlmostEqual(ns[i][2],math.sqrt(.5),places=6)
 def test_groups_do_not_leak(self):
  ns=normals(parse_obj(G+'s 1\nf 1 2 3\ns 2\nf 1 4 2\n'));self.assertNotEqual(ns[0],ns[3])
 def test_explicit_normals_override_smoothing(self):
  ns=normals(parse_obj(G+'vn 2 0 0\ns 1\nf 1//1 2//1 3//1\nf 1 4 2\n'));self.assertEqual(ns[:3],[(1.,0.,0.)]*3);self.assertAlmostEqual(ns[3][1],math.sqrt(.5),places=6)
 def test_uv_seams_and_negative_indices(self):
  mesh=parse_obj(G+'vt 0 0\nvt 1 1\ns 7\nf -4/1 -3/1 -2/1\nf -4/2 -1/2 -3/2\n');ns=normals(mesh);self.assertEqual(ns[0],ns[3]);self.assertNotEqual(mesh.vertices[6:8],mesh.vertices[30:32])
 def test_quad_fan_does_not_bias_root(self):
  text='v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nv 0 0 1\nv 1 0 1\ns 1\nf 1 2 3 4\nf 1 5 6 2\n'
  ns=normals(parse_obj(text));self.assertEqual(ns[0],ns[1]);self.assertAlmostEqual(ns[0][1],math.sqrt(.5),places=6);self.assertAlmostEqual(ns[0][2],math.sqrt(.5),places=6)
class AccessTests(unittest.TestCase):
 def test_override_existing_gates_without_payment_or_identity_claims(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);(root/'payments.json').write_text(json.dumps({'identityRequired':True}));payment=Transactions(root)
   try:
    self.assertFalse(payment.player_verified('purchase'));self.assertFalse(payment.has_access('purchase'));set_unlock_all(root,True)
    self.assertTrue(payment.player_verified('purchase'));self.assertTrue(payment.has_access('another-product'))
    self.assertFalse(payment.identity_verified('purchase'));self.assertFalse(payment.paid_once('purchase'));self.assertEqual(payment.state('purchase'),'idle')
    set_unlock_all(root,False);self.assertFalse(payment.player_verified('purchase'))
   finally:payment.close()
 def test_flag_is_boolean(self):
  with tempfile.TemporaryDirectory() as folder:
   (Path(folder)/'donation_access.json').write_text('{"unlockAll":"false"}');self.assertFalse(unlock_all(folder))
class ReleaseTests(unittest.TestCase):
 def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
 def tearDown(self):self.temp.cleanup()
 def options(self,enabled=True):return {'repository':'author/game','version':'1.2.3','publishAfterBuild':enabled}
 def test_metadata_unique_and_exact(self):
  a=make_metadata(self.root,'Game','scenes/main.json','windows-x64',self.options());b=make_metadata(self.root,'Game','scenes/main.json','windows-x64',self.options())
  self.assertNotEqual(a['buildId'],b['buildId']);self.assertEqual(a['release']['tag'],'build-'+a['buildId']);self.assertIn(a['buildId'],a['release']['asset']);self.assertEqual(a['version'],'1.2.3')
 def test_no_upload_without_opt_in(self):
  with patch('engine_releases.gh_run') as gh:self.assertIsNone(publish_build(self.root,self.options(False)));gh.assert_not_called()
 def test_auto_publish_after_success_only(self):
  with patch('engine_platform_build.export_game',return_value=self.root) as build,patch('engine_releases.publish_build') as publish:
   self.assertEqual(export_target('Windows x64',self.root,self.root,release_options=self.options()),self.root);build.assert_called_once();publish.assert_called_once()
  with patch('engine_platform_build.export_game',side_effect=ValueError('failed')),patch('engine_releases.publish_build') as publish:
   with self.assertRaises(ValueError):export_target('Windows x64',self.root,self.root,release_options=self.options())
   publish.assert_not_called()
 def test_publish_error_preserves_local_build_path(self):
  with patch('engine_platform_build.export_game',return_value=self.root),patch('engine_releases.publish_build',side_effect=RuntimeError('offline')):
   with self.assertRaises(PublicationError) as caught:export_target('Windows x64',self.root,self.root,release_options=self.options())
   self.assertEqual(caught.exception.build,self.root)
 def test_upload_archive_contains_exported_player_only(self):
  build=self.root/'built';data=build/'Data';data.mkdir(parents=True);info=make_metadata(self.root,'Game','scenes/main.json','windows-x64',self.options())
  (data/'build.json').write_text(json.dumps(info));(build/'Game.exe').write_bytes(b'test fixture');(self.root/'private-source.txt').write_text('do not publish');calls=[]
  def gh(args,**kwargs):
   calls.append(args)
   if args[0]=='api' and '/releases/tags/' in args[1]:raise RuntimeError('HTTP 404: Not Found')
   if args[:2]==['release','create']:
    with zipfile.ZipFile(args[3]) as z:self.assertEqual(set(z.namelist()),{'Data/build.json','Game.exe'});self.assertEqual(json.loads(z.read('Data/build.json'))['buildId'],info['buildId'])
    self.assertIn('--latest=false',args)
   return 'https://github.com/author/game/releases/tag/'+info['release']['tag']
  with patch('engine_releases.gh_run',side_effect=gh):publish_build(build,self.options())
  self.assertEqual(sum(args[:2]==['release','create'] for args in calls),1)
 def test_resume_draft_and_completed_upload_without_replacing_release(self):
  build=self.root/'built';data=build/'Data';data.mkdir(parents=True);info=make_metadata(self.root,'Game','main.json','windows-x64',self.options())
  (data/'build.json').write_text(json.dumps(info));(build/'Game.exe').write_bytes(b'fixture')
  existing={'body':'Build: '+info['buildId']+'\n','assets':[],'draft':True,'html_url':'https://github.com/author/game/releases/tag/example'}
  calls=[]
  def gh(args,**kwargs):
   calls.append(args)
   return json.dumps(existing) if args[0]=='api' and '/releases/tags/' in args[1] else ''
  with patch('engine_releases.gh_run',side_effect=gh):self.assertEqual(publish_build(build,self.options()),existing['html_url'])
  self.assertTrue(any(x[:2]==['release','upload'] for x in calls));self.assertTrue(any(x[:2]==['release','edit'] for x in calls));self.assertFalse(any(x[:2]==['release','create'] for x in calls))
  existing['draft']=False;existing['assets']=[{'name':info['release']['asset'],'state':'uploaded'}];calls.clear()
  with patch('engine_releases.gh_run',side_effect=gh):self.assertEqual(publish_build(build,self.options()),existing['html_url'])
  self.assertFalse(any(x[0]=='release' for x in calls))
  existing['body']='Build: a different build\n'
  with patch('engine_releases.gh_run',side_effect=gh),self.assertRaises(ValueError):publish_build(build,self.options())
 def test_repo_validation(self):
  for repo in ('https://github.com/a/b','a/../b','a/b --delete','--evil/x'):
   with self.assertRaises(ValueError):settings({'repository':repo})
 def zip(self,entries):
  path=self.root/'a.zip'
  with zipfile.ZipFile(path,'w') as z:
   for name,value in entries:z.writestr(name,value)
  return path
 def test_restore_to_new_folder_keeps_existing(self):
  parent=self.root/'downloads';parent.mkdir();old=parent/'game';old.mkdir();(old/'save.json').write_text('save')
  new=extract_archive(self.zip([('Data/build.json','{}'),('Game.exe','app')]),parent,'game');self.assertNotEqual(new,old);self.assertEqual((old/'save.json').read_text(),'save');self.assertTrue((new/'Game.exe').exists())
 def test_rejects_archive_traversal_and_duplicate_names(self):
  for entries in ([('../escape','x')],[('C:/escape','x')],[('folder/CON.txt','x')],[('one','a'),('ONE','b')]):
   with self.subTest(entries=entries),self.assertRaises(ValueError):extract_archive(self.zip(entries),self.root/'dest','game')
  self.assertFalse((self.root/'escape').exists())
 def test_rejects_archive_symlink(self):
  info=zipfile.ZipInfo('link');info.create_system=3;info.external_attr=(stat.S_IFLNK|0o777)<<16
  with self.assertRaises(ValueError):extract_archive(self.zip([(info,'/etc/passwd')]),self.root/'dest','game')
 def test_restore_uses_selected_tag_not_latest(self):
  class Response:
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def geturl(self):return 'https://release-assets.githubusercontent.com/example'
   def read(self,count):
    if hasattr(self,'sent'):return b''
    self.sent=True;return b'zip'
  data={'assets':[{'name':'Game.zip','browser_download_url':'https://github.com/author/game/releases/download/old/Game.zip','size':3}]}
  with patch('engine_releases.api_json',return_value=data) as api,patch('engine_releases.urlopen',return_value=Response()),patch('engine_releases.extract_archive',return_value=self.root/'restored'):
   result=restore_release('author/game','old/version','Game.zip',self.root);api.assert_called_once_with('repos/author/game/releases/tags/old%2Fversion');self.assertEqual(result,self.root/'restored')
if __name__=='__main__':unittest.main()
