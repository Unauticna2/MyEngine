"""Legacy UI files remain transparent without rewriting the imported asset."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from engine_ui import SlideUI, image_paths
from engine_runtime import World


class BackgroundTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.document={'format':1,'kind':'MyEngine.UI','width':960,'height':540,'startSlide':'1',
            'slides':[{'id':'1','background':'old_background.png','elements':[
                {'id':'play','image':'button.png','rect':[10,20,100,50],
                 'onClick':[{'action':'ui','enabled':False}]}]}]}
        self.path=self.root/'interface.ui.json'
        self.path.write_text(json.dumps(self.document),encoding='utf-8')

    def test_old_asset_skips_background_and_button_still_works(self):
        before=self.path.read_bytes()
        ui=SlideUI(SimpleNamespace(root=self.root),'interface.ui.json')
        self.assertFalse(ui.show_background)
        self.assertNotIn('old_background.png',ui.images)
        self.assertEqual([e['id'] for e in ui.draw_elements()],['play'])
        self.assertEqual(self.path.read_bytes(),before)
        ui.update(.01,(60,45,True,960,540));ui.update(.01,(60,45,False,960,540))
        self.assertFalse(ui.enabled)
        self.assertEqual(list(image_paths(self.document,include_background=False)),['button.png'])

    def test_background_is_explicit_opt_in_and_can_be_disabled(self):
        ui=SlideUI(SimpleNamespace(root=self.root),'interface.ui.json',show_background=True)
        self.assertEqual(ui.draw_elements()[0]['image'],'old_background.png')
        self.assertIn('old_background.png',ui.images)
        ui.show_background=False
        self.assertEqual([e['id'] for e in ui.draw_elements()],['play'])
        self.assertNotIn('old_background.png',ui.images)
        ui.show_background=True
        self.assertIn('old_background.png',ui.images)

    def test_script_load_respects_scene_choice_and_explicit_override(self):
        world=SimpleNamespace(root=self.root,ui_show_background=False,assert_thread=lambda:None)
        ui=World.load_ui(world,'interface.ui.json')
        self.assertFalse(ui.show_background)
        ui=World.load_ui(world,'interface.ui.json',show_background=True)
        self.assertTrue(ui.show_background)
        self.assertTrue(World.load_ui(world,'interface.ui.json').show_background)
        self.assertIsNone(World.load_ui(world,None))

if __name__=='__main__':unittest.main()
