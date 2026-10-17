"""Session-scoped scene callbacks, including real World transitions and editor Play."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock,patch

from engine_blueprints import generated_source,save_python
from engine_runtime import World,switch_scene,finish_frame
from engine_scene import SceneDocument

ROOT=Path(__file__).resolve().parents[1]


def graph(label):
    return {'format':1,'nodes':[
        {'id':'start','type':'Start'}, {'id':'first','type':'FirstSceneStart'},
        {'id':'a','type':'Print','params':{'text':'start:'+label}},
        {'id':'b','type':'Print','params':{'text':'first:'+label}}],
        'links':[['start','next','a','in'],['first','next','b','in']]}


class GraphTests(unittest.TestCase):
    def test_old_generated_class_can_gain_first_event_without_rewriting_custom_code(self):
        data={'format':1,'nodes':[{'id':'s','type':'Start'}],'links':[]}
        source,_=generated_source(data)
        # Simulate a file from before FirstSceneStart existed.
        source=source.replace('def _bp_first_scene_start(self, dt=0.0):\n    pass\n\n','')
        tail=source.split('# endregion MYENGINE_BLUEPRINT',1)[1]+'\nCUSTOM = 42\n'
        old=source.split('# endregion MYENGINE_BLUEPRINT',1)[0]+'# endregion MYENGINE_BLUEPRINT'+tail
        result,unused=generated_source(graph('A'),old)
        self.assertEqual(unused,[]);self.assertTrue(result.endswith(tail))
        self.assertIn('def _bp_first_scene_start(',result)

    def test_one_first_event_per_graph(self):
        data=graph('A');data['nodes'].append({'id':'extra','type':'FirstSceneStart'})
        with self.assertRaisesRegex(ValueError,'one FirstSceneStart'):generated_source(data)


@unittest.skipUnless(sys.platform=='linux','Uses the shipped native Linux core')
class FirstSceneTests(unittest.TestCase):
    def setUp(self):
        from engine_linux import LinuxCore
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.logs=[]
        self.log_patch=patch.object(World,'log',lambda world,*args:self.logs.append(' '.join(map(str,args))))
        self.log_patch.start()
        self.core=LinuxCore(ROOT,window=False);self.world=World(self.core,self.root)
        self.world.scripts_allowed=True
        self.scene('A');self.scene('B')
    def tearDown(self):
        self.world.shutdown();self.core.close();self.log_patch.stop();self.temp.cleanup()
    def scene(self,label,active=True,copies=1):
        script=self.root/(label+'.py');script.write_text(generated_source(graph(label))[0],encoding='utf-8')
        doc=SceneDocument.empty(label)
        for n in range(copies):
            i=doc.add();doc.data['names'][i]=label+str(n);doc.data['scripts'][i]=[script.name];doc.data['active'][i]=active
        doc.save(self.root/(label+'.json'));return doc
    def events(self):return [x for x in self.logs if x.startswith(('first:','start:','manual:'))]
    def switch(self,name,**kwargs):
        old=self.world;self.world=switch_scene(old,name,**kwargs);self.assertIsNot(old,self.world)
        return self.world
    def tick(self):self.world.tick(1/60,bytes(256))
    def test_A_B_A_reload_aliases_and_late_spawns_do_not_repeat(self):
        self.world.load('A.json');self.switch('B.json');self.switch('./A.json')
        self.world.reload_scene();self.world=finish_frame(self.world)
        self.world.instantiate(name='Late spawn',scripts=['A.py']);self.tick()
        self.assertEqual(self.events(),['start:A','first:A','start:B','first:B','start:A','start:A','start:A'])
    def test_every_initial_binding_gets_event_after_all_Starts(self):
        self.scene('A',copies=2);self.world.load('A.json')
        self.assertEqual(self.events(),['start:A','start:A','first:A','first:A'])
        self.world.activate();self.tick()
        self.assertEqual(self.events(),['start:A','start:A','first:A','first:A'])
    def test_f5_reload_and_direct_repeat_calls_do_not_repeat_first(self):
        self.world.load('A.json');binding=self.world.find('A0').scripts[0]
        save_python(self.root/'A.py',graph('Changed'))
        self.assertTrue(binding.reload());binding.call('first_scene_start')
        self.assertEqual(self.events(),['start:A','first:A','start:Changed'])
    def test_inactive_scene_object_runs_when_enabled_during_first_visit_only(self):
        self.scene('A',active=False);self.world.load('A.json');self.assertEqual(self.events(),[])
        self.world.find('A0').active=True;self.tick()
        self.assertEqual(self.events(),['start:A','first:A'])
        self.switch('B.json');self.switch('A.json');self.world.find('A0').active=True;self.tick()
        self.assertEqual(self.events(),['start:A','first:A','start:B','first:B','start:A'])
    def test_failed_scene_load_does_not_consume_first_visit(self):
        self.world.load('A.json');path=self.root/'B.json';valid=path.read_bytes();path.write_text('{broken')
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertIs(switch_scene(self.world,'B.json'),self.world)
        path.write_bytes(valid);self.switch('B.json')
        self.assertEqual(self.events(),['start:A','first:A','start:B','first:B'])
    def test_manual_handler_and_blueprint_each_run_once(self):
        p=self.root/'A.py';p.write_text(p.read_text()+'\ndef manual(self): self.world.log("manual:A")\nScript.first_scene_start = manual\n')
        self.world.load('A.json');self.switch('B.json');self.switch('A.json')
        self.assertEqual(self.events(),['start:A','manual:A','first:A','start:B','first:B','start:A'])
    def test_new_core_new_launch_resets_memory(self):
        from engine_linux import LinuxCore
        self.world.load('A.json');self.world.shutdown();self.core.close()
        self.core=LinuxCore(ROOT,window=False);self.world=World(self.core,self.root);self.world.load('A.json')
        self.assertEqual(self.events(),['start:A','first:A','start:A','first:A'])
    def test_editor_stop_play_and_preview_identity(self):
        from engine_editor_link import RuntimeEditor
        preview=self.root/'preview.json';preview.write_bytes((self.root/'A.json').read_bytes())
        self.core.editor_mode=True;self.world.editor_mode=True;self.world.load(preview)
        self.assertEqual(self.events(),[])
        editor=RuntimeEditor.__new__(RuntimeEditor)
        editor.gizmo=NS(cancel=Mock());editor.selected=None
        commands=[];editor.channel=NS(poll=lambda:commands[:],closed=False,send=Mock())
        def play():
            commands[:]=[{'op':'reload','path':str(preview),'play':True,'scene_identity':str(self.root/'A.json')}]
            self.world=editor.process(self.world);commands.clear()
        play();self.switch('B.json');self.switch('A.json')
        self.assertEqual(self.events(),['start:A','first:A','start:B','first:B','start:A'])
        self.world=editor.stop_play(self.world);self.assertTrue(self.world.editor_mode)
        play();self.assertEqual(self.events()[-2:],['start:A','first:A'])
    def test_png_restore_keeps_session_marks_but_new_launch_runs_first_once(self):
        from engine_saves import snapshot,read_world
        from PNGJSONUnitylity import PNGJSONUnitylity
        from engine_linux import LinuxCore
        self.world.load('A.json');frozen=snapshot(self.world)
        # Real PNG JSON roundtrip; no graphics context needed for this lifecycle check.
        from PIL import Image
        image=self.root/'save.png';Image.new('RGBA',(2,2),(0,0,0,255)).save(image)
        PNGJSONUnitylity.ToPngJson(image,frozen.encode(),png=image.read_bytes())
        data=read_world(image,self.root);self.switch('B.json');self.switch('A.json',saved=data)
        self.assertEqual(self.events(),['start:A','first:A','start:B','first:B'])
        self.world.shutdown();self.core.close();self.core=LinuxCore(ROOT,window=False)
        self.world=World(self.core,self.root);self.world.load('A.json',saved=data)
        self.assertEqual(self.events()[-1],'first:A')
        self.switch('B.json');self.switch('A.json',saved=data)
        self.assertEqual(self.events().count('first:A'),2)
    def test_snapshot_uses_real_scene_identity_in_editor_preview(self):
        from engine_saves import snapshot
        preview=self.root/'preview.json';preview.write_bytes((self.root/'A.json').read_bytes())
        self.world.load(preview,scene_identity='A.json')
        self.assertEqual(snapshot(self.world).data['sourceScene'],'A.json')
        self.switch('A.json');self.assertEqual(self.events(),['start:A','first:A','start:A'])


if __name__=='__main__':unittest.main()
