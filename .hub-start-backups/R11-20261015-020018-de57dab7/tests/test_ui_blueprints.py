"""Generated UI callbacks, real ScriptBinding lifecycle, and editor persistence."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from engine_blueprints import generated_source
from engine_runtime import ScriptBinding, World
from engine_scene import SceneDocument, atomic_json
from engine_ui import SlideUI
from engine_ui_blueprints import binding_record, click_graph, apply_binding


class UIBlueprintTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.ui_path='ui/interface.ui.json'
        self.catalog={'format':1,'kind':'MyEngine.UI','width':100,'height':100,'startSlide':'1',
            'slides':[{'id':sid,'elements':[{'id':'play','name':'Rectangle 1','rect':[10,10,30,30],
                'onClick':[]}]} for sid in ('1','2')]}
        atomic_json(self.root/self.ui_path,self.catalog)
        self.logs=[];self.scenes=[]
        self.world=NS(root=self.root,ui=None,scripts_allowed=True,editor_mode=False,
                      log=self.logs.append,load_scene=self.scenes.append,assert_thread=lambda:None,
                      ui_show_background=False)
        self.entity=NS(id=0,name='UIController',world=self.world,scripts=[],active=True,
                       destroyed=False,script_trusted=True)
        self.world.entities=[self.entity];self.world.camera=NS(scripts=[])
        self.world.ui=SlideUI(self.world,self.ui_path)
        self.bindings=[]
        self.addCleanup(self.clean_bindings)

    def clean_bindings(self):
        for binding in self.bindings:
            binding.call('on_destroy',force=True);sys.modules.pop(binding.module_name,None)

    def bind(self,data):
        path=self.root/f'handler{len(self.bindings)}.py';path.write_text(generated_source(data)[0],encoding='utf-8')
        binding=ScriptBinding(self.entity,path);self.bindings.append(binding);self.entity.scripts.append(binding)
        self.assertTrue(binding.reload(defer_start=True));binding.call('start');return binding

    def pointer(self,down,x=20,y=20):self.world.ui.update(.016,(x,y,down,100,100))
    def click(self):self.pointer(True);self.pointer(False)
    def print_graph(self,text='clicked',slide='1'):
        graph=click_graph(slide,'play','Print');graph['nodes'][1]['params']['text']=text;return graph

    def test_shape_without_json_action_becomes_button_and_fires_once(self):
        self.assertIsNone(self.world.ui.hit(20,20,100,100))
        self.bind(self.print_graph())
        self.pointer(True);self.pointer(True);self.pointer(True);self.pointer(False);self.pointer(False)
        self.assertEqual(self.logs,['clicked'])
        self.pointer(True);self.pointer(False,90,90)
        self.pointer(True,90,90);self.pointer(False)
        self.assertEqual(self.logs,['clicked'])

    def test_missing_element_is_reported_and_not_guessed(self):
        graph=self.print_graph();graph['nodes'][0]['params']['element']='2'
        self.bind(graph)
        self.assertEqual(len(self.logs),1)
        self.assertIn('UI CLICK NOT BOUND',self.logs[0]);self.assertIn('play',self.logs[0])
        self.assertIsNone(self.world.ui.hit(20,20,100,100))

    def test_blueprint_replaces_legacy_action_and_can_hide_ui(self):
        self.world.ui.slides['1']['elements'][0]['onClick']=[{'action':'scene','path':'wrong.json'}]
        self.bind(click_graph('1','play','UIVisible'));self.click()
        self.assertFalse(self.world.ui.enabled);self.assertEqual(self.scenes,[])
        self.click();self.assertEqual(self.scenes,[])

    def test_same_element_id_on_different_slides_is_scoped(self):
        self.bind(click_graph('1','play','UINextSlide'))
        self.bind(self.print_graph('second','2'))
        self.click();self.assertEqual(self.world.ui.active,'2');self.assertEqual(self.logs,[])
        self.click();self.assertEqual(self.logs,['second'])

    def test_enable_slide_show_slide_and_disable_element_chain(self):
        self.world.ui.set_slide_enabled('2',False)
        graph=click_graph('1','play','Print')
        graph['nodes'][1]={'id':'2','type':'UISlideEnabled','params':{'slide':'2','enabled':True}}
        graph['nodes'] += [{'id':'3','type':'UIShowSlide','params':{'slide':'2'}},
                          {'id':'4','type':'UIElementEnabled','params':{'slide':'2','element':'play','enabled':False}}]
        graph['links'] += [['2','next','3','in'],['3','next','4','in']]
        self.bind(graph);self.click()
        self.assertEqual(self.world.ui.active,'2')
        self.assertFalse(self.world.ui.slides['2']['elements'][0]['enabled'])

    def test_load_scene_generated_action(self):
        graph=click_graph('1','play','LoadScene');graph['nodes'][1]['params']['path']='scenes/Уровень 2.json'
        self.bind(graph);self.click();self.assertEqual(self.scenes,['scenes/Уровень 2.json'])

    def test_reload_does_not_duplicate_handlers_and_destroy_unsubscribes(self):
        binding=self.bind(self.print_graph('old'))
        for i in range(3):
            binding.path.write_text(generated_source(self.print_graph('new'))[0],encoding='utf-8')
            self.assertTrue(binding.reload(defer_start=True));binding.call('start')
        self.click();self.assertEqual(self.logs,['new'])
        self.assertEqual(len(self.world.ui._blueprints[('1','play')]),1)
        binding.call('on_destroy',force=True)
        self.assertIsNone(self.world.ui.hit(20,20,100,100))

    def test_inactive_disabled_and_untrusted_scripts_are_not_called(self):
        binding=self.bind(self.print_graph())
        for owner,attribute in [(self.entity,'active'),(self.entity,'script_trusted'),
                                (binding,'enabled'),(binding.instance,'enabled'),(self.world,'scripts_allowed')]:
            setattr(owner,attribute,False);self.click();setattr(owner,attribute,True)
        self.world.editor_mode=True;self.click();self.world.editor_mode=False
        self.assertEqual(self.logs,[])
        self.click();self.assertEqual(self.logs,['clicked'])

    def test_replacing_ui_rebinds_started_scripts(self):
        self.bind(self.print_graph())
        old=self.world.ui;World.load_ui(self.world,self.ui_path)
        self.assertIsNot(self.world.ui,old);self.click();self.assertEqual(self.logs,['clicked'])

    def test_bound_graph_does_not_handle_another_interface_with_same_ids(self):
        graph=self.print_graph();graph['ui']=self.ui_path;self.bind(graph)
        atomic_json(self.root/'ui/other.ui.json',self.catalog)
        World.load_ui(self.world,'ui/other.ui.json');self.click();self.assertEqual(self.logs,[])
        World.load_ui(self.world,self.ui_path);self.click();self.assertEqual(self.logs,['clicked'])

    def document(self):
        document=SceneDocument.empty('Menu');document.data['ui']=self.ui_path;return document

    def test_apply_creates_controller_preserves_import_and_user_python(self):
        document=self.document();before=(self.root/self.ui_path).read_bytes()
        record=binding_record(document,self.root,self.ui_path,'1','play')
        record,_=apply_binding(document,self.root,record,self.print_graph())
        self.assertEqual(len(document.data['model']),1);self.assertFalse(document.data['visible'][0])
        self.assertEqual(document.data['scripts'][0],[record['script']])
        path=self.root/record['script'];path.write_text(path.read_text()+'\nCUSTOM = 42\n',encoding='utf-8')
        document.data['names'][0]='Renamed controller';document.data['scriptTrusted'][0]=False
        record,_=apply_binding(document,self.root,record,self.print_graph('updated'))
        self.assertEqual(record['object'],'Renamed controller');self.assertEqual(len(document.data['model']),1)
        self.assertFalse(document.data['scriptTrusted'][0]);self.assertIn('CUSTOM = 42',path.read_text())
        self.assertEqual((self.root/self.ui_path).read_bytes(),before)
        document.save(self.root/'scene.json')
        loaded=SceneDocument.load(self.root/'scene.json')
        self.assertEqual(binding_record(loaded,self.root,self.ui_path,'1','play'),record)
        self.assertTrue(document.undo());self.assertNotEqual(document.data,loaded.data)

    def test_validation_and_failed_apply_keep_previous_files_and_scene(self):
        document=self.document();record=binding_record(document,self.root,self.ui_path,'1','play')
        record,_=apply_binding(document,self.root,record,self.print_graph())
        before=deepcopy(document.data);bp=self.root/record['graph'];py=self.root/record['script']
        files={bp:bp.read_bytes(),py:py.read_bytes()}
        from engine_ui_blueprints import replace_bytes
        calls=[]
        def fail_python(path,data):
            calls.append(path)
            if len(calls)==2:raise OSError('locked script')
            return replace_bytes(path,data)
        with patch('engine_ui_blueprints.replace_bytes',side_effect=fail_python):
            with self.assertRaisesRegex(OSError,'locked script'):apply_binding(document,self.root,record,self.print_graph('new'))
        self.assertEqual(document.data,before)
        for path,data in files.items():self.assertEqual(path.read_bytes(),data)
        bad=click_graph('1','play','LoadScene');bad['nodes'][1]['params']['path']='missing.json'
        with self.assertRaises(FileNotFoundError):apply_binding(document,self.root,record,bad)
        self.assertEqual(document.data,before)
        for path,data in files.items():self.assertEqual(path.read_bytes(),data)


if __name__=='__main__':unittest.main()
