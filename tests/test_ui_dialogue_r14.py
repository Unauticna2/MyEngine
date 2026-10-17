"""Dialogue input limits and persistence. Does not require a Tk display."""
from pathlib import Path
from types import SimpleNamespace
import json,tempfile,unittest

from engine_ui import SlideUI,load_document
from engine_ui_content import dialogue
from engine_ui_content_editor import apply_element,dialogue_lines,dialogue_feedback


class DialogueInputTests(unittest.TestCase):
    def test_line_endings_and_whitespace_separators(self):
        for newline in ('\n','\r\n','\r'):
            with self.subTest(newline=repr(newline)):
                text=newline.join(['Первый абзац','внутри реплики',' \t','', 'Вторая реплика','','Третья'])
                self.assertEqual(dialogue_lines(text),['Первый абзац\nвнутри реплики','Вторая реплика','Третья'])

    def test_empty_input_explains_enable_checkbox(self):
        message,invalid=dialogue_feedback(' \n\t\n',True)
        self.assertTrue(invalid);self.assertIn('нет реплик',message)
        self.assertIn('сними галочку',message);self.assertIn('0/1000',message)

    def test_disabled_dialogue_does_not_require_text(self):
        message,invalid=dialogue_feedback('',False)
        self.assertFalse(invalid);self.assertIn('Новелла выключена',message)
        self.assertIsNone(dialogue(None))

    def test_long_entry_reports_its_number_and_actual_length(self):
        message,invalid=dialogue_feedback('Первая\n\n'+'я'*4097,True)
        self.assertTrue(invalid);self.assertIn('№2',message)
        self.assertIn('4097',message);self.assertIn('пустой строкой',message)

    def test_limit_accepts_unicode_without_truncation(self):
        text='Я🙂'*2048
        parsed=dialogue({'lines':[text]})
        self.assertEqual(parsed['lines'],[text])
        message,invalid=dialogue_feedback(text,True)
        self.assertFalse(invalid);self.assertIn('4096/4096',message)

    def test_maximum_entries_and_overflow(self):
        self.assertEqual(len(dialogue({'lines':['a']*1000})['lines']),1000)
        with self.assertRaisesRegex(ValueError,'1001 реплик'):
            dialogue({'lines':['a']*1001})

    def test_bad_json_and_nul_are_distinct(self):
        cases=[('text','объектом JSON'),({'lines':'text'},'списком строк'),
               ({'lines':['ok',42]},'№2 должна быть строкой'),
               ({'lines':['ok','a\0b']},'№2 есть нулевой символ')]
        for value,message in cases:
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,message):dialogue(value)


class DialoguePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.path=self.root/'ui.json'
        self.data={'format':1,'kind':'MyEngine.UI','width':100,'height':100,'startSlide':'2',
            'slides':[{'id':'2','elements':[{'id':'9','rect':[0,0,90,90],
                'textSlot':{'rect':[2,2,80,80],'sourceText':'Текст'},
                'dialogue':{'lines':['Сохранено ранее']}}]}]}
        self.path.write_text(json.dumps(self.data),encoding='utf-8')

    def test_rejected_edit_leaves_saved_ui_unchanged(self):
        before=self.path.read_bytes()
        with self.assertRaisesRegex(ValueError,'Слайд 2, элемент 9: Новелла: реплика №2'):
            apply_element(self.path,'2','9',{'dialogue':{'lines':['ok','x'*4097]}})
        self.assertEqual(self.path.read_bytes(),before)

    def test_file_load_identifies_element_and_error(self):
        self.data['slides'][0]['elements'][0]['dialogue']={'lines':[]}
        self.path.write_text(json.dumps(self.data),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Слайд 2, элемент 9: Новелла: нет реплик'):
            load_document(self.path)

    def test_split_save_and_click_show_next_replica(self):
        lines=dialogue_lines('Первая\r\nстрока\r\n \t\r\nВторая')
        apply_element(self.path,'2','9',{'dialogue':dialogue({'lines':lines})})
        ui=SlideUI(SimpleNamespace(root=self.root),'ui.json');self.addCleanup(ui.close)
        element=ui.slides['2']['elements'][0]
        self.assertEqual(ui.content.text(element),'Первая\nстрока')
        ui.update(0,(10,10,True,100,100));ui.update(0,(10,10,False,100,100))
        self.assertEqual(ui.content.text(element),'Вторая')

    def test_disable_novel_and_save_anchors(self):
        result=apply_element(self.path,'2','9',{'dialogue':None,'anchors':{'horizontal':'left'}})
        element=result['slides'][0]['elements'][0]
        self.assertIsNone(element['dialogue']);self.assertEqual(element['anchors']['horizontal'],'left')
        self.assertIsNone(load_document(self.path)['slides'][0]['elements'][0]['dialogue'])


if __name__=='__main__':unittest.main()
