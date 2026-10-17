"""Background recovery through the real importer and editor checkbox callbacks.

PowerPoint/Windows and Tk display are not available on the Linux test host.
Only those boundaries are simulated, not the importer or callback logic.
"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch, Mock

import engine_pptx_import as importer
import engine_settings_ui as dialogs
from engine_ui import SlideUI


class ImportBackgroundTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.commands=[];self.version=1;self.omit=None
        self.source=self.root/'Menu.pptx';self.source.write_bytes(b'original presentation')
        self.engine=Path(importer.__file__).parent
        self.data={'format':1,'kind':'MyEngine.UI','width':100,'height':100,'sourcePresentation':'Menu.pptx','startSlide':'1',
                   'slides':[{'id':str(i),'sourceSlideId':str(255+i),'elements':[
                       {'id':'play','sourceShapeId':'2','image':f'button{i}.png','rect':[10,10,30,30]}]} for i in (1,2)]}
        for context in [patch.object(importer,'_powershell',return_value='powershell.exe'),
                        patch.object(importer.subprocess,'run',side_effect=self.export)]:
            context.start();self.addCleanup(context.stop)
    def export(self,command,**kwargs):
        self.commands.append(command);stage=Path(command[command.index('-Output')+1]);data=deepcopy(self.data)
        for slide in data['slides']:
            (stage/slide['elements'][0]['image']).write_bytes(b'button')
            if '-IncludeBackground' in command and self.omit!='field':
                slide['background']='bg'+slide['id']+'.png'
                if self.omit!='image':(stage/slide['background']).write_bytes(f'background v{self.version}'.encode())
        (stage/'interface.ui.json').write_text(json.dumps(data))
        (stage/'_powerpoint_source.json').write_text(json.dumps({'directory':str(self.root),'source':str(self.source)}))
        return NS(returncode=0,stdout=b'',stderr=b'')
    def test_default_does_not_export_or_display_background(self):
        path,_=importer.import_powerpoint(None,self.root,'Menu')
        self.assertNotIn('-IncludeBackground',self.commands[-1]);self.assertFalse(importer.has_backgrounds(path))
        self.assertEqual([e['id'] for e in SlideUI(NS(root=self.root),path).draw_elements()],['play'])
    def test_checked_new_import_exports_background_but_visibility_is_scene_owned(self):
        path,_=importer.import_powerpoint(None,self.root,'Menu',include_background=True)
        self.assertIn('-IncludeBackground',self.commands[-1]);self.assertTrue(importer.has_backgrounds(path))
        ui=SlideUI(NS(root=self.root),path);self.assertEqual([e['id'] for e in ui.draw_elements()],['play'])
        ui.show_background=True;self.assertEqual([e['id'] for e in ui.draw_elements()],['_background','play'])
        self.assertEqual(self.source.read_bytes(),b'original presentation')
    def test_upgrade_old_import_and_refresh_while_hidden_keeps_current_background(self):
        path,_=importer.import_powerpoint(None,self.root,'Menu');relative=path.relative_to(self.root)
        importer.update_powerpoint(relative,self.root,include_background=True,required=[('1','play')])
        self.assertTrue(importer.has_backgrounds(path));before=path.read_bytes()
        self.version=2;importer.update_powerpoint(relative,self.root,include_background=False)
        self.assertIn('-IncludeBackground',self.commands[-1])
        self.assertEqual((path.parent/'bg1.png').read_bytes(),b'background v2')
        self.assertEqual(path.read_bytes(),before)
        self.assertIn('-Source',self.commands[-1])
        self.assertEqual(self.commands[-1][self.commands[-1].index('-Source')+1],str(self.source))
    def test_missing_background_file_is_detected_on_any_slide(self):
        path,_=importer.import_powerpoint(None,self.root,'Menu',include_background=True)
        (path.parent/'bg2.png').unlink();self.assertFalse(importer.has_backgrounds(path))
    def test_failed_background_export_keeps_previous_asset_and_source_map(self):
        for omission in ['field','image']:
            with self.subTest(omission=omission):
                self.omit=None;path,_=importer.import_powerpoint(None,self.root,omission)
                before={p.relative_to(path.parent):p.read_bytes() for p in path.parent.rglob('*') if p.is_file()}
                registry=self.root/'.myengine/ui-sources.json';source_map=registry.read_bytes();self.omit=omission
                with self.assertRaises((RuntimeError,FileNotFoundError)):
                    importer.update_powerpoint(path,self.root,include_background=True)
                self.assertEqual(before,{p.relative_to(path.parent):p.read_bytes() for p in path.parent.rglob('*') if p.is_file()})
                self.assertEqual(source_map,registry.read_bytes());self.assertFalse(importer._IMPORT_LOCK.locked())
                self.assertFalse(list(path.parent.parent.glob('.pptx-*')))


class Var:
    def __init__(self,value=None):self.value=value
    def get(self):return self.value
    def set(self,value):self.value=value


class Widget:
    def __init__(self,widgets,**kwargs):self.options=kwargs;self.widgets=widgets;widgets.append(self)
    def pack(self,**kwargs):pass
    def configure(self,**kwargs):self.options.update(kwargs)
    def title(self,*args):pass
    def geometry(self,*args):pass
    def minsize(self,*args):pass
    def transient(self,*args):pass
    def protocol(self,*args):pass
    def after(self,ms,callback):self.poll=callback
    def winfo_exists(self):return True


class CheckboxTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.ui='assets/ui/Menu/interface.ui.json';path=self.root/self.ui;path.parent.mkdir(parents=True)
        self.data={'format':1,'kind':'MyEngine.UI','width':100,'height':100,'startSlide':'1','slides':[{'id':'1','elements':[]}]}
        path.write_text(json.dumps(self.data));self.widgets=[];self.jobs=[];self.errors=[]
        document=NS(data={'ui':self.ui,'uiBackground':False},checkpoint=Mock())
        self.editor=NS(window=None,path_root=self.root,document=document,can_edit=lambda:True,
                       changed=Mock(),reload=Mock(),refresh_project=Mock(),error=self.errors.append,log=Mock())
        factory=lambda *a,**k:Widget(self.widgets,**k)
        def thread(*,target,**kwargs):return NS(start=lambda:self.jobs.append(target))
        for context in [patch.object(dialogs,'tk',NS(Toplevel=factory,BooleanVar=Var,StringVar=Var)),
                        patch.object(dialogs,'ttk',NS(Frame=factory,Label=factory,Checkbutton=factory,Button=factory)),
                        patch.object(dialogs,'threading',NS(Thread=thread)),
                        patch.object(dialogs.messagebox,'showerror',side_effect=lambda *a,**k:self.errors.append(a)),
                        patch.object(dialogs.messagebox,'showinfo')]:
            context.start();self.addCleanup(context.stop)
        dialogs.ui_dialog(self.editor);self.window=self.widgets[0]
        self.checkbox=self.control('Показывать фон слайда / Show slide background')
        self.background=self.checkbox.options['variable']
    def control(self,text):return next(w for w in self.widgets if w.options.get('text')==text)
    def toggle(self,value):self.background.set(value);self.checkbox.options['command']()
    def finish(self):self.jobs.pop(0)();self.window.poll()
    def cache_background(self):
        self.data['slides'][0]['background']='bg.png';(self.root/self.ui).write_text(json.dumps(self.data))
        (self.root/self.ui).with_name('bg.png').write_bytes(b'cached')
    def test_old_import_enabling_fetches_then_commits_and_reloads_once(self):
        def update(*args,**kwargs):self.cache_background();return self.root/self.ui,[]
        with patch.object(importer,'update_powerpoint',side_effect=update) as call:
            self.toggle(True)
            self.assertFalse(self.editor.document.data['uiBackground'])
            self.assertEqual(self.checkbox.options['state'],'disabled');self.assertEqual(len(self.jobs),1)
            self.finish()
        self.assertTrue(call.call_args.kwargs['include_background'])
        self.assertTrue(self.editor.document.data['uiBackground']);self.assertTrue(self.background.get())
        self.editor.reload.assert_called_once();self.assertEqual(self.checkbox.options['state'],'normal')
    def test_powerpoint_failure_restores_checkbox_and_does_not_reload(self):
        with patch.object(importer,'update_powerpoint',side_effect=RuntimeError('Open PowerPoint first')):
            self.toggle(True);self.finish()
        self.assertFalse(self.background.get());self.assertFalse(self.editor.document.data['uiBackground'])
        self.editor.reload.assert_not_called();self.assertEqual(len(self.errors),1)
    def test_cached_background_off_on_needs_no_powerpoint(self):
        self.cache_background()
        for value in [True,False,True]:
            self.toggle(value);self.assertEqual(self.editor.document.data['uiBackground'],value)
        self.assertEqual(self.jobs,[]);self.assertEqual(self.editor.reload.call_count,3)
    def test_missing_image_refetches_even_when_json_has_background_field(self):
        self.cache_background();(self.root/self.ui).with_name('bg.png').unlink()
        self.toggle(True);self.assertEqual(len(self.jobs),1)
    def test_completed_job_cannot_enable_background_in_another_scene(self):
        with patch.object(importer,'update_powerpoint',return_value=(self.root/self.ui,[])):
            self.toggle(True);self.editor.document=NS(data={'ui':self.ui,'uiBackground':False},checkpoint=Mock())
            self.finish()
        self.assertFalse(self.editor.document.data['uiBackground']);self.assertFalse(self.background.get())
        self.editor.reload.assert_not_called()
    def test_update_button_and_new_import_pass_current_checkbox(self):
        self.cache_background();self.toggle(True);self.editor.reload.reset_mock()
        with patch.object(importer,'update_powerpoint',return_value=(self.root/self.ui,[])) as update:
            self.control('Обновить текущий UI из PowerPoint').options['command']();self.finish()
            self.assertTrue(update.call_args.kwargs['include_background'])
        with patch.object(dialogs.simpledialog,'askstring',return_value='NewMenu'), \
             patch.object(importer,'import_powerpoint',return_value=(self.root/'assets/ui/NewMenu/interface.ui.json',[])) as create:
            self.control('Import from open PowerPoint…').options['command']();self.finish()
            self.assertTrue(create.call_args.kwargs['include_background'])
            self.assertEqual(self.editor.document.data['ui'],'assets/ui/NewMenu/interface.ui.json')


if __name__=='__main__':unittest.main()
