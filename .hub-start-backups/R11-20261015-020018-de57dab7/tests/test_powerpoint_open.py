"""Importer transaction/IPC tests. No installed PowerPoint is simulated as real."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import engine_pptx_import as importer
from engine_ui import SlideUI

DOCUMENT = {'format':1,'kind':'MyEngine.UI','width':960,'height':540,
    'sourcePresentation':'2DInteface.pptx','startSlide':'1','warnings':[],
    'slides':[{'id':'1','elements':[
        {'id':'play','image':'button.png','rect':[10,20,100,50],
         'onClick':[{'action':'ui','enabled':False}]}]}]}


class OpenPowerPointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source_dir = self.root/'Презентации & файлы'
        self.source_dir.mkdir()
        self.source = self.source_dir/'2DInteface.pptx'
        self.source.write_bytes(b'original: never modify')
        self.engine = self.root/'Движок & scripts'
        (self.engine/'tools').mkdir(parents=True)
        (self.engine/'tools/powerpoint_export.ps1').write_text('placeholder')
        self.document = copy.deepcopy(DOCUMENT)
        self.commands = []

    def fake_process(self, command, **kwargs):
        self.commands.append((command, kwargs))
        stage = Path(command[command.index('-Output')+1])
        (stage/'interface.ui.json').write_text(json.dumps(self.document),encoding='utf-8')
        (stage/'_powerpoint_source.json').write_text(json.dumps({'directory':str(self.source_dir)}))
        (stage/'button.png').write_bytes(b'exported button')
        return SimpleNamespace(returncode=0,stdout=b'Exported 1 slides.',stderr=b'')

    def import_deck(self, process=None, source=None):
        with patch.object(importer,'_powershell',return_value='powershell.exe'), \
             patch.object(importer.subprocess,'run',side_effect=process or self.fake_process):
            return importer.import_powerpoint(source,self.root,'Menu',self.engine)

    def assert_clean(self):
        self.assertFalse((self.root/'assets/ui/Menu').exists())
        self.assertFalse(list((self.root/'assets/ui').glob('.pptx-*')))
        self.assertFalse(importer._IMPORT_LOCK.locked())

    def test_active_import_preserves_original_and_ui_click(self):
        path,warnings = self.import_deck()
        self.assertEqual(self.source.read_bytes(),b'original: never modify')
        self.assertFalse((path.parent/'_powerpoint_source.json').exists())
        self.assertEqual(warnings,[])
        cmd,kw = self.commands[0]
        self.assertNotIn('-Source',cmd)
        self.assertIn('-STA',cmd)
        self.assertNotIn('shell',kw)
        ui = SlideUI(SimpleNamespace(root=self.root),path.relative_to(self.root))
        ui.update(.01,(60,45,True,960,540))
        ui.update(.01,(60,45,False,960,540))
        self.assertFalse(ui.enabled)
        with self.assertRaises(FileExistsError): self.import_deck()

    def test_named_open_file_passed_as_single_argument(self):
        self.import_deck(source=self.source)
        cmd,kw = self.commands[0]
        self.assertEqual(cmd[cmd.index('-Source')+1],str(self.source))
        self.assertEqual(cmd[cmd.index('-File')+1],str(self.engine/'tools/powerpoint_export.ps1'))

    def test_missing_output_even_exit_zero_does_not_publish(self):
        with self.assertRaises(FileNotFoundError):
            self.import_deck(lambda *a,**k:SimpleNamespace(returncode=0,stdout=b'',stderr=b''))
        self.assert_clean()

    def test_com_failure_keeps_stage_details_and_cleans_asset(self):
        error=b"PowerPoint export failed at stage 'creating a snapshot': HRESULT 0x80029C4A"
        with self.assertRaisesRegex(RuntimeError,'0x80029C4A'):
            self.import_deck(lambda *a,**k:SimpleNamespace(returncode=1,stdout=b'',stderr=error))
        self.assert_clean()

    def test_timeout_never_kills_powerpoint_process(self):
        def timeout(cmd,**kwargs):
            self.commands.append(cmd)
            raise subprocess.TimeoutExpired(cmd,kwargs['timeout'])
        with self.assertRaisesRegex(RuntimeError,'временная презентация'):
            self.import_deck(timeout)
        self.assertEqual(len(self.commands),1)
        self.assertEqual(self.commands[0][0],'powershell.exe')
        self.assert_clean()

    def test_partial_output_invalid_document_does_not_publish(self):
        self.document['slides'][0]['elements'].append(copy.deepcopy(self.document['slides'][0]['elements'][0]))
        with self.assertRaisesRegex(ValueError,'Duplicate UI element'):
            self.import_deck()
        self.assert_clean()

    def test_frames_copied_from_original_directory(self):
        frames=self.source_dir/'frames';frames.mkdir();(frames/'1.png').write_bytes(b'frame')
        self.document['slides'][0]['elements'][0]['frames']=['frames/1.png']
        path,_=self.import_deck()
        self.assertEqual((path.parent/'frames/1.png').read_bytes(),b'frame')

    def test_frame_traversal_rejected(self):
        self.document['slides'][0]['elements'][0]['frames']=['../../secret.png']
        with self.assertRaises(ValueError):self.import_deck()
        self.assert_clean()

    def test_missing_generated_image_not_replaced_by_source_file(self):
        (self.source_dir/'button.png').write_bytes(b'wrong image')
        def process(cmd,**kwargs):
            result=self.fake_process(cmd,**kwargs)
            (Path(cmd[cmd.index('-Output')+1])/'button.png').unlink()
            return result
        with self.assertRaises(FileNotFoundError):self.import_deck(process)
        self.assert_clean()

    def test_cleanup_warning_kept_after_successful_export(self):
        def process(cmd,**kwargs):
            result=self.fake_process(cmd,**kwargs)
            result.stderr=b'Cleanup warning: snapshot still open'
            return result
        path,warnings=self.import_deck(process)
        self.assertIn('snapshot still open',warnings[0])
        self.assertEqual(json.loads(path.read_text())['warnings'],warnings)

    def test_parallel_import_does_not_start_second_export(self):
        importer._IMPORT_LOCK.acquire()
        try:
            with self.assertRaisesRegex(RuntimeError,'ещё выполняется'):
                self.import_deck()
            self.assertEqual(self.commands,[])
        finally:importer._IMPORT_LOCK.release()

if __name__=='__main__':unittest.main()
