"""LibreOffice import regressions; fake conversion tests do not require Office."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile
import xml.etree.ElementTree as ET
from engine_pptx_layers import NS, tag, xml_bytes, metadata, prepare_layers
import engine_pptx_libreoffice as importer
from engine_ui import SlideUI


def fixture(path, content=None):
    meta = content or {'myengine': {'id': 'play', 'onClick': [{'action': 'ui', 'enabled': False}]}}
    p = ET.Element(tag('p:presentation'))
    ids = ET.SubElement(p, tag('p:sldIdLst'))
    ET.SubElement(ids, tag('p:sldId'), {'id': '256', tag('r:id'): 's1'})
    ET.SubElement(p, tag('p:sldSz'), {'cx': '12192000', 'cy': '6858000'})
    rels = ET.Element(tag('rel:Relationships'))
    ET.SubElement(rels, tag('rel:Relationship'), {'Id': 's1', 'Type': NS['r']+'/slide', 'Target': 'slides/slide1.xml'})
    slide = ET.Element(tag('p:sld'))
    cs = ET.SubElement(slide, tag('p:cSld'))
    tree = ET.SubElement(cs, tag('p:spTree'))
    ET.SubElement(tree, tag('p:nvGrpSpPr'))
    ET.SubElement(tree, tag('p:grpSpPr'))
    sp = ET.SubElement(tree, tag('p:sp'))
    nv = ET.SubElement(sp, tag('p:nvSpPr'))
    ET.SubElement(nv, tag('p:cNvPr'), {'id': '2', 'name': 'Button'})
    props = ET.SubElement(sp, tag('p:spPr'))
    transform = ET.SubElement(props, tag('a:xfrm'), {'rot': '1800000'})
    ET.SubElement(transform, tag('a:off'), {'x': '127000', 'y': '254000'})
    ET.SubElement(transform, tag('a:ext'), {'cx': '1270000', 'cy': '635000'})
    body = ET.SubElement(sp, tag('p:txBody'))
    para = ET.SubElement(body, tag('a:p'))
    run = ET.SubElement(para, tag('a:r'))
    ET.SubElement(run, tag('a:t')).text = json.dumps(meta)
    types = ET.Element(tag('ct:Types'))
    for name in ('/ppt/presentation.xml', '/ppt/slides/slide1.xml'):
        ET.SubElement(types, tag('ct:Override'), {'PartName': name, 'ContentType': 'application/xml'})
    with zipfile.ZipFile(path, 'w') as z:
        for name, node in {'ppt/presentation.xml': p, 'ppt/_rels/presentation.xml.rels': rels,
                           'ppt/slides/slide1.xml': slide, '[Content_Types].xml': types}.items():
            z.writestr(name, xml_bytes(node))
    return sp


class LibreOfficeImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root/'интерфейс & test.pptx'
        self.shape = fixture(self.source)

    def test_inline_json_and_rotation_preserved(self):
        before = self.source.read_bytes()
        deck = self.root/'layers.pptx'
        document, tasks = prepare_layers(self.source, deck)
        element = document['slides'][0]['elements'][0]
        self.assertEqual(element['id'], 'play')
        self.assertEqual(element['rect'], [10.,20.,100.,50.])
        self.assertEqual(element['rotation'], 30.)
        self.assertEqual([t['type'] for t in tasks], ['background','black','white'])
        with zipfile.ZipFile(deck) as z:
            layer = ET.fromstring(z.read('ppt/slides/myengine_render_2.xml'))
            self.assertEqual(layer.find('.//p:sp/p:spPr/a:xfrm',NS).get('rot'), '0')
            self.assertFalse(''.join(n.text or '' for n in layer.findall('.//a:t',NS)))
            self.assertIn(b'<Types xmlns=', z.read('[Content_Types].xml'))
        self.assertEqual(self.source.read_bytes(), before)

    def test_alt_text_has_priority_and_visible_caption_retained(self):
        self.shape.find('.//p:cNvPr',NS).set('descr', '{"myengine":{"id":"alt"}}')
        value, inline = metadata(self.shape)
        self.assertEqual(value['id'], 'alt')
        self.assertFalse(inline)

    def test_plain_text_not_parsed_as_code(self):
        self.shape.find('.//a:t',NS).text = 'Играть'
        self.assertEqual(metadata(self.shape), ({},False))

    def test_invalid_metadata_reports_shape(self):
        self.shape.find('.//a:t',NS).text = '{"myengine": broken}'
        with self.assertRaisesRegex(ValueError, 'Button'):
            metadata(self.shape)

    def test_macro_rejected(self):
        with zipfile.ZipFile(self.source, 'a') as z:z.writestr('ppt/vbaProject.bin',b'payload')
        with self.assertRaisesRegex(ValueError, 'Macro-enabled'):
            prepare_layers(self.source,self.root/'layers.pptx')

    def test_layered_ui_click_disables_ui(self):
        doc, _ = prepare_layers(self.source,self.root/'layers.pptx')
        doc['slides'][0]['elements'][0]['imageRect'] = [-10,-10,120,70]
        (self.root/'ui.json').write_text(json.dumps(doc))
        ui = SlideUI(SimpleNamespace(root=self.root),'ui.json')
        self.assertIsNotNone(ui.hit(60,45,960,540))
        self.assertIsNone(ui.hit(0,0,960,540))
        ui.update(.01,(60,45,True,960,540))
        ui.update(.01,(60,45,False,960,540))
        self.assertFalse(ui.enabled)

    def fake_render(self, pdf, tasks, doc, output):
        for task in tasks:
            if task['type']=='background':(output/task['file']).write_bytes(b'png')
            if task['type']=='white':(output/task['element']['image']).write_bytes(b'png')

    def import_fake(self, convert=None):
        with patch.object(importer,'find_libreoffice',return_value='/soffice'), \
             patch.object(importer,'_dependencies'), \
             patch.object(importer,'_convert',side_effect=convert or (lambda *a: self.root/'render.pdf')), \
             patch.object(importer,'_render_pdf',side_effect=self.fake_render):
            return importer.import_powerpoint(self.source,self.root,'Menu')

    def test_import_transaction_does_not_overwrite_existing(self):
        path,warnings = self.import_fake()
        self.assertTrue(path.is_file())
        with self.assertRaises(FileExistsError):self.import_fake()
        self.assertFalse(list((self.root/'assets/ui').glob('.pptx-*')))

    def test_conversion_failure_removes_partial_asset(self):
        def fail(*args):raise RuntimeError('converter failed')
        with self.assertRaisesRegex(RuntimeError,'converter failed'):self.import_fake(fail)
        self.assertFalse((self.root/'assets/ui/Menu').exists())
        self.assertFalse(list((self.root/'assets/ui').glob('.pptx-*')))

    def test_missing_pdf_is_error_even_with_zero_exit(self):
        work=self.root/'conversion';work.mkdir()
        process=SimpleNamespace(returncode=0,communicate=lambda **kw:(b'',b'Error: load failed'))
        with patch.object(importer.subprocess,'Popen',return_value=process) as popen:
            with self.assertRaisesRegex(RuntimeError,'load failed'):
                importer._convert('/soffice',self.source,work,2)
        command=popen.call_args.args[0]
        self.assertIn('--headless',command)
        self.assertTrue(any(s.startswith('-env:UserInstallation=file:') for s in command))
        self.assertEqual(command[-1],str(self.source))
        self.assertNotIn('shell',popen.call_args.kwargs)

    def test_explicit_missing_executable(self):
        with self.assertRaises(FileNotFoundError):importer.find_libreoffice(self.root/'missing.exe')

    def test_white_object_and_transparency_recovered(self):
        try:from PIL import Image
        except ImportError:self.skipTest('Pillow is optional')
        sprite=Image.new('RGBA',(8,8),(0,0,0,0))
        sprite.putpixel((2,2),(255,255,255,255))
        sprite.putpixel((3,3),(120,70,30,128))
        black=Image.alpha_composite(Image.new('RGBA',sprite.size,(0,0,0,255)),sprite)
        white=Image.alpha_composite(Image.new('RGBA',sprite.size,(255,255,255,255)),sprite)
        recovered,bounds=importer._recover_sprite(black,white)
        self.assertEqual(bounds,(2,2,4,4))
        self.assertEqual(recovered.getpixel((0,0)),(255,255,255,255))
        rgba=recovered.getpixel((1,1))
        self.assertTrue(all(abs(x-y)<=2 for x,y in zip(rgba,(120,70,30,128))),rgba)
        self.assertEqual(recovered.getpixel((1,0))[3],0)


if __name__=='__main__':unittest.main()
