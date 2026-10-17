"""Scene creation, persistence and editor transitions without a GUI display."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from engine_projects import create_scene, project_scenes
from engine_scene import SceneDocument, DEFAULTS
from MyEngine2Editor import Editor


class NewSceneTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'Проект';self.root.mkdir()

    def editor(self,dirty=False):
        editor=Editor.__new__(Editor)
        editor.path_root=self.root;editor.path=self.root/'old.json'
        editor.document=SceneDocument({'model':[None],'names':['Old'],
            'ui':'old.ui.json','skybox':'old.png','camera':{'position':{'y':100}}})
        editor.document.save(editor.path)
        editor.saved=copy.deepcopy(editor.document.data)
        if dirty:editor.document.add()
        editor.selected=0;editor.playing=False;editor.gizmo_active=False;editor.edit_transaction=None
        editor.preview=self.root/'.myengine/preview.json';editor.write_preview()
        editor.channel=None;editor.authenticated=False;editor.pending=[]
        editor.window=Mock();editor.log=Mock();editor.error=Mock()
        editor.populate_hierarchy=Mock();editor.show_inspector=Mock();editor.refresh_project=Mock()
        return editor

    def test_create_reopen_and_discover_scene_without_inherited_assets(self):
        path,document=create_scene(self.root,'scenes/Новая зона.json')
        self.assertEqual(SceneDocument.load(path).data,document.data)
        self.assertEqual(document.data['title'],'Новая зона')
        for key in DEFAULTS:self.assertEqual(document.data[key],[])
        self.assertTrue(document.data['camera']['freeFly'])
        self.assertNotIn('ui',document.data);self.assertNotIn('skybox',document.data)
        self.assertEqual(project_scenes(self.root),['scenes/Новая зона.json'])
        path,_=create_scene(self.root,'scenes/Upper.JSON')
        self.assertEqual(path.name,'Upper.json');self.assertIn('scenes/Upper.json',project_scenes(self.root))

    def test_existing_file_and_paths_outside_project_are_preserved(self):
        path,_=create_scene(self.root,'scenes/Level.json');before=path.read_bytes()
        with self.assertRaises(FileExistsError):create_scene(self.root,path)
        self.assertEqual(path.read_bytes(),before)
        for name in ('../outside.json','scenes/bad.txt','scenes/CON.json','project.myengine.json','scenes/button.ui.json'):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):create_scene(self.root,name)
        self.assertFalse((self.root.parent/'outside.json').exists())

    def test_failed_write_removes_incomplete_new_file(self):
        with patch('engine_scene.os.fsync',side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError,'disk full'):create_scene(self.root,'scenes/Failed.json')
        self.assertFalse((self.root/'scenes/Failed.json').exists())

    def test_editor_creates_saved_scene_reloads_viewport_and_clears_selection(self):
        editor=self.editor();original=editor.path.read_bytes()
        self.assertTrue(editor.new_scene('scenes/Level2.json'))
        self.assertEqual(editor.path,self.root/'scenes/Level2.json')
        self.assertEqual(editor.saved,editor.document.data)
        self.assertEqual(SceneDocument.load(editor.preview).data,editor.document.data)
        self.assertEqual(editor.document.undo_stack,[]);self.assertIsNone(editor.selected)
        self.assertEqual((self.root/'old.json').read_bytes(),original)
        self.assertEqual(editor.pending,[{'op':'reload','path':str(editor.preview),'play':False},
                                         {'op':'select','name':None}])
        editor.populate_hierarchy.assert_called_once();editor.show_inspector.assert_called_once()
        editor.refresh_project.assert_called_once();editor.error.assert_not_called()

    def test_unsaved_cancel_and_save_failure_keep_current_scene(self):
        editor=self.editor(dirty=True);original=editor.document;preview=editor.preview.read_bytes()
        with patch('MyEngine2Editor.messagebox.askyesnocancel',return_value=None):
            self.assertFalse(editor.new_scene('scenes/Cancel.json'))
        with patch('MyEngine2Editor.messagebox.askyesnocancel',return_value=True), \
             patch.object(editor.document,'save',side_effect=OSError('read only')):
            self.assertFalse(editor.new_scene('scenes/Cancel.json'))
        self.assertIs(editor.document,original);self.assertEqual(editor.preview.read_bytes(),preview)
        self.assertFalse((self.root/'scenes/Cancel.json').exists());self.assertEqual(editor.pending,[])

    def test_save_or_discard_unsaved_edits_before_creation(self):
        for save in (True,False):
            with self.subTest(save=save):
                editor=self.editor(dirty=True);old=editor.path
                with patch('MyEngine2Editor.messagebox.askyesnocancel',return_value=save):
                    self.assertTrue(editor.new_scene(f'scenes/New{save}.json'))
                self.assertEqual(len(SceneDocument.load(old).data['model']),2 if save else 1)

    def test_name_dialog_cancel_or_existing_name_keeps_editor_state(self):
        editor=self.editor();original=editor.document;old_path=editor.path
        with patch('MyEngine2Editor.filedialog.asksaveasfilename',return_value=''):
            self.assertFalse(editor.new_scene())
        self.assertFalse(editor.new_scene(old_path))
        self.assertIs(editor.document,original);self.assertEqual(editor.path,old_path)
        self.assertEqual(editor.pending,[]);editor.error.assert_called_once()

    def test_play_and_pending_object_changes_block_scene_creation(self):
        for attribute in ('playing','gizmo_active','edit_transaction'):
            editor=self.editor();setattr(editor,attribute,True)
            self.assertFalse(editor.new_scene('scenes/Blocked.json'))
        self.assertFalse((self.root/'scenes/Blocked.json').exists())

    def test_reopening_scene_clears_old_selection(self):
        editor=self.editor();target,_=create_scene(self.root,'scenes/Next.json')
        editor.open_scene(target)
        self.assertEqual(editor.path,target);self.assertIsNone(editor.selected)
        self.assertEqual(editor.pending[-1],{'op':'select','name':None})
        editor.error.assert_not_called()


if __name__=='__main__':unittest.main()
