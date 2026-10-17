"""Actual Tk menus / checkbox / scene persistence. Run with DISPLAY (e.g. Xvfb)."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

import MyEngine2Editor as ui
from engine_collider_editor import collider_data
from engine_scene import SceneDocument

ROOT=Path(__file__).resolve().parents[1]


class LegacyColliderTests(unittest.TestCase):
    def test_supported_legacy_forms_preserve_shape_and_extensions(self):
        for absent in (None,False):self.assertIsNone(collider_data(absent))
        for value in (True,'box',{}):
            self.assertEqual(collider_data(value),{'type':'box','enabled':True,'isTrigger':False})
        value={'kind':'voxel','is_trigger':True,'enabled':False,'wSize':.4,'layer':3,
               'mask':8,'size':[2,3,4],'center':[1,0,0],'friction':.3,'restitution':.5,'custom':'keep'}
        original=deepcopy(value);result=collider_data(value)
        self.assertEqual(value,original);self.assertTrue(result['isTrigger'])
        self.assertEqual(result['type'],'voxel');self.assertNotIn('is_trigger',result)
        for key in set(value)-{'kind','is_trigger'}:self.assertEqual(result[key],value[key])


@unittest.skipUnless(os.environ.get('DISPLAY') or sys.platform=='win32','Requires an actual Tk display')
class EditorContextTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root_path=Path(self.temp.name)
        (self.root_path/'assets').mkdir();shutil.copy2(ROOT/'assets/Cube.obj',self.root_path/'assets/Cube.obj')
        shutil.copy2(ROOT/'assets/VoxelSphere.vxl.json',self.root_path/'assets/VoxelSphere.vxl.json')
        self.path=self.root_path/'scene.json';SceneDocument.empty().save(self.path)
        self.patcher=patch.object(ui,'ROOT',self.root_path);self.patcher.start()
        self.root=tk.Tk();self.callback_errors=[]
        self.root.report_callback_exception=lambda *args:self.callback_errors.append(args)
        self.editor=ui.Editor(self.root,self.path,launch=False)
        self.errors=[];self.editor.error=lambda error:self.errors.append(str(error))
        self.root.update()
    def tearDown(self):
        try:
            self.assertEqual(self.callback_errors,[])
        finally:
            for task in self.root.tk.splitlist(self.root.tk.call('after','info')):
                self.root.after_cancel(task)
            self.editor.saved=deepcopy(self.editor.document.data)
            self.editor.close();self.patcher.stop();self.temp.cleanup()

    def popup(self,widget,x=10,y=10):
        widget.event_generate('<Button-3>',x=x,y=y);self.root.update()
        menu=self.editor._object_popup
        self.assertTrue(menu.winfo_exists());self.assertTrue(menu.winfo_ismapped())
        return menu

    def submenu(self,menu,label):return self.root.nametowidget(menu.entrycget(label,'menu'))

    def add_empty(self):
        self.editor.add('empty');self.root.update()

    def test_right_click_blank_hierarchy_creates_cube_and_menu_stays_open(self):
        menu=self.popup(self.editor.hierarchy)
        self.assertEqual(menu.entrycget('Add component','state'),'disabled')
        self.submenu(menu,'Create').invoke('Cube');menu.unpost();self.root.update()
        self.assertEqual(self.editor.document.data['model'],['assets/Cube.obj'])
        self.assertEqual(self.editor.selected,0)

    def test_first_scene_start_is_addable_in_real_blueprint_palette(self):
        from engine_blueprint_ui import BlueprintEditor
        blueprint=BlueprintEditor(self.root,self.root_path,data={'format':1,'nodes':[],'links':[]})
        self.assertIn('FirstSceneStart',blueprint.kind_box.cget('values'))
        blueprint.kind.set('FirstSceneStart');blueprint.add();self.root.update()
        self.assertEqual(blueprint.data['nodes'][0]['type'],'FirstSceneStart')
        self.assertIn('def _bp_first_scene_start(',blueprint.preview.get('1.0','end'))
        self.assertTrue(any(p[1:4]==('next','out','exec') for p in blueprint.ports.values()))

    def test_create_primitives_in_empty_project_copies_missing_assets_only(self):
        for name,kind in [('Cube.obj','cube'),('VoxelSphere.vxl.json','voxel')]:
            path=self.root_path/'assets'/name;path.unlink()
            menu=self.editor.object_context_menu();self.submenu(menu,'Create').invoke(kind.title());menu.destroy()
            self.assertEqual(path.read_bytes(),(ROOT/'assets'/name).read_bytes())
            original=path.read_bytes()+b'\n';path.write_bytes(original)
            self.editor.add(kind);self.assertEqual(path.read_bytes(),original)

    def test_right_click_row_targets_that_object_and_creates_lights_and_voxels(self):
        self.add_empty();self.add_empty()
        box=self.editor.hierarchy.bbox('0')
        menu=self.popup(self.editor.hierarchy,y=box[1]+box[3]//2)
        self.assertEqual(self.editor.selected,0)
        self.submenu(menu,'Add component').invoke('Box Collider');menu.unpost();self.root.update()
        self.assertEqual(self.editor.document.data['colliders'][0]['type'],'box')
        self.assertIsNone(self.editor.document.data['colliders'][1])
        for command in ('Directional Light','Point Light','Spot Light'):
            menu=self.editor.object_context_menu()
            self.submenu(self.submenu(menu,'Create'),'Light').invoke(command);menu.destroy()
        menu=self.editor.object_context_menu();self.submenu(menu,'Create').invoke('Voxel');menu.destroy()
        self.assertTrue(self.editor.document.data['voxels'][-1])
        self.assertEqual([v['type'] for v in self.editor.document.data['lights'][2:5]],['directional','point','spot'])

    def test_inspector_child_right_click_adds_rigidbody_with_visible_box_collider(self):
        self.add_empty();inspector=self.editor.inspector_vars['colliders']
        menu=self.popup(inspector.help)
        self.submenu(menu,'Add component').invoke('Rigidbody');menu.unpost();self.root.update()
        obj=self.editor.document.object(0)
        self.assertEqual(obj['rigidbodies']['mass'],1);self.assertEqual(obj['colliders']['type'],'box')
        control=self.editor.inspector_vars['colliders'].trigger_check
        self.assertTrue(control.winfo_ismapped());self.assertFalse(control.instate(['disabled']))
        self.assertLess(control.winfo_rooty(),self.editor.inspector_canvas.winfo_rooty()+180)

    def test_checkbox_updates_document_immediately_save_reload_undo_redo_and_preserves_data(self):
        self.add_empty()
        obj=self.editor.document.object(0)
        obj['colliders']={'type':'box','size':[2,3,4],'center':[1,0,0],'layer':3,'mask':31,'wSize':.2,'friction':.4,'custom':{'keep':True}}
        self.editor.document.set_object(0,obj);self.editor.show_inspector();self.root.update()
        before=deepcopy(obj['colliders']);control=self.editor.inspector_vars['colliders']
        control.trigger_check.invoke();self.root.update()
        data=self.editor.document.data['colliders'][0];self.assertTrue(data['isTrigger'])
        for key,value in before.items():self.assertEqual(data[key],value)
        self.assertTrue(self.editor.save());self.assertTrue(SceneDocument.load(self.path).data['colliders'][0]['isTrigger'])
        self.editor.undo();self.assertFalse(self.editor.inspector_vars['colliders'].trigger.get())
        self.editor.redo();self.assertTrue(self.editor.inspector_vars['colliders'].trigger.get())
        self.editor.inspector_vars['colliders'].enabled_check.invoke()
        self.assertFalse(self.editor.document.data['colliders'][0]['enabled'])
        self.editor.inspector_vars['colliders'].trigger_check.invoke()
        self.assertFalse(self.editor.document.data['colliders'][0]['isTrigger'])

    def test_invalid_component_does_not_modify_document_or_add_undo(self):
        self.editor.add('cube');before=deepcopy(self.editor.document.data);undos=len(self.editor.document.undo_stack)
        self.editor.add_component('voxel')
        self.assertIn('voxel model',self.errors[-1])
        self.assertEqual(self.editor.document.data,before);self.assertEqual(len(self.editor.document.undo_stack),undos)
        self.editor.add_component('mesh');self.assertEqual(self.editor.document.data['colliders'][0]['type'],'mesh')
        before=deepcopy(self.editor.document.data);self.editor.add_component('rigidbody')
        self.assertIn('Dynamic bodies',self.errors[-1]);self.assertEqual(self.editor.document.data,before)

    def test_play_blocks_menu_and_checkbox_changes(self):
        self.add_empty();self.editor.add_component('box')
        self.editor.playing=True;before=deepcopy(self.editor.document.data)
        menu=self.editor.object_context_menu()
        self.assertEqual(menu.entrycget('Create','state'),'disabled')
        self.assertEqual(menu.entrycget('Add component','state'),'disabled');menu.destroy()
        self.editor.inspector_vars['colliders'].trigger_check.invoke()
        self.assertFalse(self.editor.inspector_vars['colliders'].trigger.get())
        self.assertEqual(before,self.editor.document.data);self.editor.playing=False

    def test_advanced_apply_and_invalid_json_do_not_conflict_with_checkbox(self):
        self.add_empty();self.editor.add_component('box');control=self.editor.inspector_vars['colliders']
        control.extra.delete('1.0','end');control.extra.insert('1.0','{"size":[4,5,6],"mask":7}')
        self.assertTrue(self.editor.apply());control.trigger_check.invoke()
        self.assertEqual(self.editor.document.data['colliders'][0]['size'],[4,5,6])
        before=deepcopy(self.editor.document.data)
        control.extra.delete('1.0','end');control.extra.insert('1.0','{"size":')
        control.trigger_check.invoke()
        self.assertTrue(self.errors);self.assertEqual(self.editor.document.data,before)
        self.assertTrue(control.trigger.get())

    def test_saved_checkbox_drives_actual_physics_blueprint_event(self):
        if sys.platform!='linux':self.skipTest('Native Linux physics integration')
        from engine_blueprints import generated_source
        from engine_linux import LinuxCore
        from engine_runtime import World
        self.add_empty();self.editor.add_component('box')
        self.editor.inspector_vars['colliders'].trigger_check.invoke()
        graph={'format':1,'nodes':[{'id':'e','type':'OnTriggerEnter'},
               {'id':'a','type':'Print','params':{'text':'checkbox -> trigger'}}],
               'links':[['e','next','a','in']]}
        (self.root_path/'event.py').write_text(generated_source(graph)[0],encoding='utf-8')
        self.editor.inspector_vars['scripts'].insert('1.0','event.py');self.assertTrue(self.editor.apply())
        self.add_empty();self.editor.add_component('box');self.assertTrue(self.editor.save())
        core=LinuxCore(ROOT,window=False);world=World(core,self.root_path);logs=[];world.log=logs.append
        try:
            world.scripts_allowed=True;world.load(self.path);world.camera.position=(100,100,100);logs.clear()
            world.tick(world.physics.fixed_delta_time,bytes(256))
            self.assertEqual(logs,['checkbox -> trigger'])
        finally:world.shutdown();core.close()


if __name__=='__main__':unittest.main()
