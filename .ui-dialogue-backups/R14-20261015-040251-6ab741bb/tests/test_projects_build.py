import json
from pathlib import Path
import struct
import tempfile
import unittest
from engine_projects import create_project,read_project,Registry,project_scenes,safe_name
from engine_build import export_game,validate_project,is_x64_pe

ENGINE=Path(__file__).resolve().parent.parent
def pe(export=False):
    b=bytearray(80);b[:2]=b'MZ';struct.pack_into('<I',b,60,64);b[64:70]=b'PE\0\0d\x86'
    return bytes(b)+(b'EnginePortableV1\0EngineGetRuntimeFlags\0' if export else b'')

class ProjectTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_project_create_registry_and_no_overwrite(self):
        p=create_project(ENGINE,self.root,'Тестовый проект');meta=read_project(p)
        self.assertEqual(meta['mainScene'],'scenes/main.json');self.assertEqual(project_scenes(p),['scenes/main.json'])
        r=Registry(self.root/'recent.json');r.remember(p);r.remember(p);self.assertEqual(len(r.entries),1)
        r.forget(p);self.assertTrue(p.exists());self.assertEqual(r.entries,[])
        with self.assertRaises(FileExistsError):create_project(ENGINE,self.root,'Тестовый проект')
    def test_external_assets_rejected(self):
        p=create_project(ENGINE,self.root,'Game');scene=p/'scenes/main.json';d=json.loads(scene.read_text());d['model'][0]='../outside.obj';scene.write_text(json.dumps(d))
        with self.assertRaises(ValueError):validate_project(p,'scenes/main.json')
    def test_windows_names(self):
        for name in ('','../game','game/one','CON','NUL.exe','A|B','A.'):
            with self.assertRaises(ValueError):safe_name(name)
    def test_export_layout_is_relocatable(self):
        # Synthetic PE fixtures validate packaging only; they are not executable players.
        p=create_project(ENGINE,self.root,'Game');tool=self.root/'engine';tool.mkdir()
        (tool/'MyEngine2.exe').write_bytes(pe(True));(tool/'engine_runtime.py').write_text('# fixture');(tool/'PNGJSONUnitylity.py').write_text('# fixture')
        (tool/'MyEngineVideo.dll').write_bytes(b'video managed DLL fixture');(tool/'tools').mkdir();(tool/'tools/video_host.ps1').write_text('# video host fixture')
        (tool/'MyEngineUI.dll').write_bytes(pe());(tool/'engine_ui_native.py').write_text('# native binding fixture')
        (tool/'shaders').mkdir();(tool/'shaders/voxel.frag').write_text('// fixture')
        home=self.root/'python';(home/'Lib/encodings').mkdir(parents=True);(home/'DLLs').mkdir()
        (home/'python313.dll').write_bytes(pe());(home/'vcruntime140.dll').write_bytes(pe())
        (home/'Lib/encodings/__init__.py').write_text('# fixture');(home/'LICENSE.txt').write_text('fixture license')
        out=export_game(tool,p,p/'Builds','Release','scenes/main.json',python_home=home)
        self.assertEqual(sorted(x.name for x in out.iterdir()),['Data','Release.exe'])
        ini=(out/'Data/python.ini').read_text(encoding='utf-16');self.assertNotIn(str(self.root),ini)
        self.assertIn('Home=.\\Python',ini);self.assertTrue((out/'Data/assets/Cube.obj').is_file())
        self.assertEqual(json.loads((out/'Data/build.json').read_text())['mainScene'],'scenes/main.json')
        self.assertEqual((out/'Data/MyEngineUI.dll').read_bytes(),pe())
        self.assertTrue((out/'Data/engine_ui_native.py').is_file())
        self.assertEqual((out/'Data/MyEngineVideo.dll').read_bytes(),b'video managed DLL fixture')
        self.assertTrue((out/'Data/tools/video_host.ps1').is_file())
        self.assertFalse((out/'Data/Builds').exists());self.assertFalse((out/'Data/project.myengine.json').exists())
        with self.assertRaises(FileExistsError):export_game(tool,p,p/'Builds','Release','scenes/main.json',python_home=home)
        before=list((p/'Builds').iterdir());(home/'vcruntime140.dll').unlink()
        with self.assertRaises(ValueError):export_game(tool,p,p/'Builds','Failed','scenes/main.json',python_home=home)
        self.assertEqual(list((p/'Builds').iterdir()),before)
    def test_old_exe_rejected(self):
        p=create_project(ENGINE,self.root,'Game');tool=self.root/'engine';tool.mkdir();(tool/'MyEngine2.exe').write_bytes(pe())
        with self.assertRaisesRegex(ValueError,'Rebuild'):export_game(tool,p,p/'Builds','Game','scenes/main.json',python_home=self.root)

if __name__=='__main__':unittest.main()
