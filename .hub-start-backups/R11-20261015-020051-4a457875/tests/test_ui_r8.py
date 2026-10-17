"""UI transitions, animation triggers, reimport and application exit."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
import zipfile
import xml.etree.ElementTree as ET

from engine_ui import SlideUI
from engine_ui_effects import loads_metadata,normalize_quotes,enrich_snapshot
from engine_ui_reimport import merge_document
from engine_blueprints import generated_source
from engine_ui_blueprints import click_graph
from engine_runtime import finish_frame,World,ScriptBinding
from engine_runtime_options import normalized,native_flags
import engine_pptx_import as importer


def catalog():
    return {'format':1,'kind':'MyEngine.UI','width':100,'height':100,'startSlide':'1','sourcePresentation':'Menu.pptx',
        'slides':[{'id':str(i),'sourceSlideId':str(255+i),'elements':[{'id':'play','sourceShapeId':'2','rect':[10,10,30,30],
        'image':f'slide_{i}_shape_2.png','animations':[{'kind':'spin','duration':1.,'degrees':360}]}]} for i in (1,2)]}


class UIEffectsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.data=catalog();self.path=self.root/'interface.ui.json';self.world=NS(root=self.root)
    def ui(self):
        self.path.write_text(json.dumps(self.data));return SlideUI(self.world,self.path)
    def click(self,ui):ui.update(0,(20,20,True,100,100));ui.update(0,(20,20,False,100,100))
    def test_fade_draws_both_slides_and_blocks_clicks_until_finished(self):
        ui=self.ui();self.assertTrue(ui.show_slide('2',transition='fade',duration=1))
        self.assertEqual(ui.active,'2');self.assertIsNone(ui.hit(20,20,100,100))
        ui.update(.5);items=ui.render_items();self.assertEqual(len(items),2)
        self.assertEqual([pose[-1] for _,pose in items],[.5,.5])
        ui.update(.5);self.assertIsNone(ui._transition);self.assertEqual(len(ui.render_items()),1)
    def test_push_offsets_and_previous_disabled_slide(self):
        ui=self.ui();ui.next_slide(transition='push',duration=1,direction='left');ui.update(.5)
        self.assertEqual([pose[0] for _,pose in ui.render_items()],[-40,60])
        ui.update(.5);self.assertTrue(ui.previous_slide(transition='none'));self.assertEqual(ui.active,'1')
        ui.set_slide_enabled('2',False);self.assertFalse(ui.next_slide())
    def test_automatic_slide_advance(self):
        self.data['slides'][0]['advanceAfter']=.25
        ui=self.ui();ui.update(.25);self.assertEqual(ui.active,'2')
    def test_click_animation_waits_restarts_and_remains_clickable_without_action(self):
        self.data['slides'][0]['elements'][0]['animationMode']='click';ui=self.ui();e=ui.slides['1']['elements'][0]
        ui.update(4);self.assertEqual(ui.pose(e)[4],0);self.assertIs(ui.hit(20,20,100,100),e)
        self.click(ui);ui.update(.5);self.assertAlmostEqual(ui.pose(e)[4],180)
        self.click(ui);self.assertAlmostEqual(ui.pose(e)[4],0)
    def test_loop_auto_manual_modes(self):
        for mode,expected in [('auto',360),('loop',90),('manual',0)]:
            self.data['slides'][0]['elements'][0]['animationMode']=mode;ui=self.ui();ui.update(1.25)
            e=ui.slides['1']['elements'][0];self.assertAlmostEqual(ui.pose(e)[4],expected)
            ui.play_animation('play','1');ui.update(.5);self.assertAlmostEqual(ui.pose(e)[4],180)
    def test_powerpoint_shape_trigger_animates_other_element(self):
        e=self.data['slides'][0]['elements'][0];e['animations']=[]
        other=dict(e,id='target',rect=[60,60,20,20]);self.data['slides'][0]['elements'].append(other)
        self.data['slides'][0]['animations']=[{'element':'target','kind':'spin','duration':1,'degrees':360,'triggerElement':'play','triggerGroup':'sequence1'}]
        ui=self.ui();ui.update(5);target=ui.slides['1']['elements'][1];self.assertEqual(ui.pose(target)[4],0)
        self.click(ui);ui.update(.5);self.assertAlmostEqual(ui.pose(target)[4],180)
    def test_automatic_group_order_is_sequential(self):
        e=self.data['slides'][0]['elements'][0];e['animationMode']='auto'
        e['animations']=[{'kind':'spin','group':1,'duration':1,'degrees':90},{'kind':'spin','group':2,'duration':1,'degrees':90}]
        ui=self.ui();ui.update(.5);self.assertAlmostEqual(ui.pose(ui.slides['1']['elements'][0])[4],45)
        ui.update(1);self.assertAlmostEqual(ui.pose(ui.slides['1']['elements'][0])[4],135)
    def test_action_waits_for_click_animation_and_is_not_repeated(self):
        e=self.data['slides'][0]['elements'][0];e.update(animationMode='click',waitForAnimation=True,onClick=[{'action':'slide','slide':'2'}])
        ui=self.ui();self.click(ui);self.assertEqual(ui.active,'1')
        ui.update(.5);self.click(ui);self.assertEqual(ui.active,'1')
        ui.update(.5);self.assertEqual(ui.active,'2');self.assertIsNone(ui._pending_click)
    def test_frames_stop_on_last_frame_in_once_mode(self):
        e=self.data['slides'][0]['elements'][0];e.update(animationMode='click',frames=['a.png','b.png'],fps=2)
        ui=self.ui();element=ui.slides['1']['elements'][0];ui.update(5);self.assertEqual(ui.frame_index(element),0)
        self.click(ui);ui.update(4);self.assertEqual(ui.frame_index(element),1)
    def test_blueprint_animation_and_quit_compile_and_run(self):
        graph=click_graph('1','play','UIPlayAnimation');graph['nodes'].append({'id':'3','type':'QuitGame'});graph['links'].append(['2','next','3','in'])
        code,_=generated_source(graph);scope={};exec(code,scope)
        ui=self.ui();requests=[];obj=NS(world=NS(ui=ui,quit=lambda:requests.append('quit')))
        scope['_bp_ui_click'](obj,'1','play');self.assertEqual(requests,['quit']);self.assertIn('play',ui._manual_starts)


class QuoteAndSnapshotTests(unittest.TestCase):
    def test_curly_delimiters_preserve_unicode_inside_standard_strings(self):
        for start,end in [('“','”'),('„','“'),('«','»')]:
            self.assertEqual(loads_metadata('{'+start+'myengine'+end+': {'+start+'id'+end+': '+start+'play'+end+'}}'),{'myengine':{'id':'play'}})
        text='{"text":"Он сказал “играть” и «выйти»; a\u00a0b"}'
        self.assertEqual(normalize_quotes(text),text)
    def test_actual_pptx_xml_transition_and_stable_ids(self):
        from test_pptx_import import fixture
        from engine_pptx_layers import tag,xml_bytes
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'deck.pptx';fixture(path)
            with zipfile.ZipFile(path) as z:parts={n:z.read(n) for n in z.namelist()}
            slide=ET.fromstring(parts['ppt/slides/slide1.xml'])
            tr=ET.SubElement(slide,tag('p:transition'),{'{http://schemas.microsoft.com/office/powerpoint/2010/main}dur':'800','advTm':'2500','advClick':'0'})
            ET.SubElement(tr,tag('p:push'),{'dir':'r'});parts['ppt/slides/slide1.xml']=xml_bytes(slide)
            with zipfile.ZipFile(path,'w') as z:
                for name,content in parts.items():z.writestr(name,content)
            data=catalog();data['slides']=data['slides'][:1];enrich_snapshot(path,data)
            s=data['slides'][0];self.assertEqual(s['sourceSlideId'],'256');self.assertEqual(s['transition'],{'kind':'push','direction':'right','duration':.8})
            self.assertEqual(s['advanceAfter'],2.5);self.assertFalse(s['advanceOnClick'])


class ReimportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.document=catalog();self.version=1
        self.mock=patch.object(importer,'_run_export',side_effect=self.export);self.mock.start();self.addCleanup(self.mock.stop)
    def export(self,source,stage,engine,timeout):
        (stage/'interface.ui.json').write_text(json.dumps(self.document))
        (stage/'_powerpoint_source.json').write_text(json.dumps({'directory':str(self.root),'source':str(self.root/'Menu.pptx')}))
        for i in (1,2):(stage/f'slide_{i}_shape_2.png').write_bytes(f'PNG v{self.version}'.encode())
        return ''
    def test_updates_same_path_preserves_ids_settings_and_extra_files(self):
        path,_=importer.import_powerpoint(None,self.root,'Menu');old=json.loads(path.read_text())
        old['slides'][0]['elements'][0].update(animationMode='click',_editor={'animationMode':'click'})
        path.write_text(json.dumps(old));(path.parent/'my_notes.txt').write_text('keep')
        self.version=2;self.document['slides'][0]['elements'][0]['id']='renamed_in_powerpoint'
        updated,_=importer.update_powerpoint(path,self.root,required=[('1','play')])
        self.assertEqual(updated,path);new=json.loads(path.read_text());e=new['slides'][0]['elements'][0]
        self.assertEqual(e['id'],'play');self.assertEqual(e['animationMode'],'click');self.assertEqual((path.parent/'my_notes.txt').read_text(),'keep')
        self.assertEqual((path.parent/'slide_1_shape_2.png').read_bytes(),b'PNG v2')
        self.assertTrue(list((self.root/'.myengine/ui-backups').glob('*/interface.ui.json')))
        self.assertNotIn(str(self.root),path.read_text())
    def test_removed_bound_button_rejects_update_without_touching_asset(self):
        path,_=importer.import_powerpoint(None,self.root,'Menu');before=path.read_bytes()
        self.document['slides'][0]['elements']=[]
        with self.assertRaisesRegex(ValueError,'Blueprint'):importer.update_powerpoint(path,self.root,required=[('1','play')])
        self.assertEqual(path.read_bytes(),before);self.assertFalse(importer._IMPORT_LOCK.locked())
    def test_failed_swap_restores_previous_asset_and_source_mapping(self):
        path,_=importer.import_powerpoint(None,self.root,'Menu');before=path.read_bytes();registry=self.root/'.myengine/ui-sources.json';info=registry.read_bytes()
        rename=Path.rename
        def fail(source,dest):
            if source.name.startswith('.pptx-'):raise OSError('simulated locked asset')
            return rename(source,dest)
        with patch.object(Path,'rename',fail):
            with self.assertRaisesRegex(OSError,'locked'):importer.update_powerpoint(path,self.root)
        self.assertEqual(path.read_bytes(),before);self.assertEqual(registry.read_bytes(),info)
        self.assertFalse(list(path.parent.parent.glob('.pptx-*')))
    def test_new_slide_before_existing_preserves_old_slide_id(self):
        old=catalog();new=deepcopy(old);new['slides'][0]['id']='2';new['slides'][1]['id']='3'
        new['slides'].insert(0,{'id':'1','sourceSlideId':'999','elements':[]})
        result=merge_document(old,new,required=[('1','play')])
        self.assertEqual([s['id'] for s in result['slides']],['slide_999','1','2'])
    def test_legacy_import_shape_filename_preserves_button_name(self):
        old=catalog();old['slides'][0].pop('sourceSlideId');old['slides'][0]['elements'][0].pop('sourceShapeId')
        new=catalog();new['slides'][0]['elements'][0]['id']='2'
        self.assertEqual(merge_document(old,new)['slides'][0]['elements'][0]['id'],'play')


class QuitTests(unittest.TestCase):
    def test_escape_off_in_game_and_editor(self):
        self.assertFalse(native_flags(normalized())&4);self.assertFalse(native_flags(normalized(),editor=True)&4)
    def test_quit_prioritizes_exit_over_pending_scene_and_uses_platform_hook(self):
        calls=[];world=NS(quit_requested=True,pending_scene='other.json',core=NS(request_quit=lambda:calls.append('closed')))
        self.assertIs(finish_frame(world),world);self.assertEqual(calls,['closed']);self.assertIsNone(world.pending_scene)
    def test_editor_quit_uses_stop_play_not_process_exit(self):
        calls=[];world=NS(quit_requested=True,pending_scene=None,core=NS(request_quit=lambda:self.fail('Must not close editor viewport')))
        editor=NS(stop_play=lambda w:(calls.append('stopped') or w))
        finish_frame(world,editor);self.assertEqual(calls,['stopped'])

if __name__=='__main__':unittest.main()
