"""Invalid target feedback and committing parameter fields before generation."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from engine_blueprint_ui import BlueprintEditor
from engine_ui_blueprints import click_graph, validate_click_targets


class UIClickFixTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.catalog={'slides':[{'id':'1','elements':[{'id':'play'}]}]}

    def test_shape_number_is_rejected_with_actual_id(self):
        with self.assertRaisesRegex(ValueError,"element '2'.*Available element IDs: play"):
            validate_click_targets(click_graph('1','2'),self.catalog)
        validate_click_targets(click_graph('1','play'),self.catalog)

    def editor(self):
        editor=BlueprintEditor.__new__(BlueprintEditor)
        editor.root=self.root;editor.path=self.root/'button.blueprint.json'
        editor.data=click_graph('1','play','LoadScene');editor.selected='2'
        editor.param_vars={'path':NS(get=lambda:'scenes/room1.json')}
        editor.ui_data=self.catalog;editor.dirty=False;editor.draw=lambda:None
        editor.errors=[];editor.error=editor.errors.append;editor.status=NS(set=lambda _:None)
        return editor

    def test_save_commits_field_without_extra_apply_button(self):
        editor=self.editor()
        self.assertTrue(editor.save(),editor.errors)
        saved=json.loads(editor.path.read_text())
        self.assertEqual(saved['nodes'][1]['params']['path'],'scenes/room1.json')
        self.assertFalse(editor.dirty)

    def test_save_does_not_write_unmatched_button(self):
        editor=self.editor();editor.data['nodes'][0]['params']['element']='2'
        self.assertFalse(editor.save());self.assertFalse(editor.path.exists())
        self.assertIn('play',str(editor.errors[0]))

    def test_unchanged_fields_do_not_mark_graph_dirty(self):
        editor=self.editor();editor.data['nodes'][1]['params']['path']='scenes/room1.json'
        self.assertTrue(editor.apply());self.assertFalse(editor.dirty)

    def test_generic_blueprint_window_receives_imported_ui_catalog(self):
        from engine_editor_tools import blueprint_dialog
        catalog=dict(self.catalog,format=1,kind='MyEngine.UI',width=960,height=540)
        catalog['slides'][0]['elements'][0]['rect']=[20,340,180,160]
        (self.root/'interface.ui.json').write_text(json.dumps(catalog))
        errors=[]
        editor=NS(can_edit=lambda:True,path_root=self.root,window=None,
                  document=NS(data={'ui':'interface.ui.json'}),error=errors.append)
        with patch('engine_blueprint_ui.BlueprintEditor') as window:
            blueprint_dialog(editor,self.root/'button.blueprint.json')
            self.assertFalse(errors)
            self.assertEqual(window.call_args.kwargs['ui_data'],catalog)


if __name__=='__main__':unittest.main()
