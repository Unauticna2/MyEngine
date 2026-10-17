"""Anchors/clicks, dialogue flow, PPTX media extraction and asynchronous payments.
Windows COM/GDI/WPF playback requires the integration checklist on Windows.
"""
from concurrent.futures import Future
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch,Mock
import json,tempfile,threading,time,unittest,zipfile
from engine_ui import SlideUI,validate,image_paths
from engine_ui_content import media_paths
from engine_ui_layout import anchors,rect
from engine_ui_blueprints import click_graph
from engine_ui_reimport import merge_document
from engine_ui_content_editor import apply_element
from engine_blueprints import Graph,generated_source
from engine_ui_media import youtube_url,video_settings,VideoPlayer
from engine_transactions import Transactions
from engine_ui_text import TextTextures,raster
from engine_pptx_media import enrich_media


def catalog():
    return {'format':1,'kind':'MyEngine.UI','width':100,'height':100,'startSlide':'1','slides':[
        {'id':'1','sourceSlideId':'256','elements':[{'id':'box','sourceShapeId':'2','rect':[10,60,80,30],'color':[.2,.2,.2,1],'textSlot':{'rect':[4,4,72,22],'sourceText':'Текст','style':{'size':10}},'dialogue':{'lines':['Привет, мир!','Следующая реплика'],'clickToAdvance':True}}]},
        {'id':'2','sourceSlideId':'257','elements':[]}]}

class UITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.data=catalog();self.path=self.root/'ui.json';self.path.write_text(json.dumps(self.data))
        self.world=NS(root=self.root,log=Mock(),core=NS(create_texture=Mock(return_value=1),delete_texture=Mock()),editor_mode=False,scripts_allowed=True)
        self.ui=SlideUI(self.world,'ui.json');self.addCleanup(self.ui.close)
    def click(self,x,y,w=100,h=100):
        self.ui.update(0,(x,y,True,w,h));self.ui.update(0,(x,y,False,w,h))
    def test_dialogue_click_moves_one_line_then_finishes_once(self):
        e=self.ui.slides['1']['elements'][0];e['onDialogueEnd']=[{'action':'next'}]
        self.assertEqual(self.ui.content.text(e),'Привет, мир!');self.click(40,70)
        self.assertEqual(self.ui.content.text(e),'Следующая реплика');self.assertFalse(self.ui.dialogue_finished('box'))
        self.click(40,70);self.assertEqual(self.ui.active,'2');self.assertTrue(self.ui.dialogue_finished('box','1'))
        self.assertFalse(self.ui.dialogue_next('box','1'));self.ui.dialogue_reset('box','1')
        self.assertFalse(self.ui.dialogue_finished('box','1'));self.assertEqual(self.ui.content.text(e,'1'),'Привет, мир!')
    def test_manual_text_and_loop(self):
        e=self.ui.slides['1']['elements'][0];e['dialogue']['loop']=True
        self.ui.set_text('box','Свой текст');self.assertEqual(self.ui.content.text(e),'Свой текст')
        self.ui.dialogue_next('box');self.assertEqual(self.ui.content.text(e),'Следующая реплика')
        self.ui.dialogue_next('box');self.assertEqual(self.ui.content.text(e),'Привет, мир!');self.assertFalse(self.ui.dialogue_finished('box'))
    def test_blueprint_does_not_double_advance(self):
        e=self.ui.slides['1']['elements'][0]
        b=NS(started=True,enabled=True,instance=NS(enabled=True),entity=NS(active=True,destroyed=False,script_trusted=True),call=lambda *a:self.ui.dialogue_next('box'))
        self.ui._blueprints[('1','box')]=[b];self.click(40,70)
        self.assertEqual(self.ui.content.text(e),'Следующая реплика');self.assertFalse(self.ui.dialogue_finished('box'))
    def test_none_settings_and_old_ui_remain_valid(self):
        e=self.ui.slides['1']['elements'][0];e['dialogue']=None;e['video']=None
        self.ui._video_autoplay_done=False;self.ui.update(.1);self.assertIsNone(self.ui.hit(40,70,100,100))
        d=catalog();d['slides'][0]['elements'][0].update(dialogue=None,video=None);validate(d)
    def test_anchors_share_render_and_hit_transform_in_letterbox(self):
        e=self.ui.slides['1']['elements'][0];e['rect']=[75,70,20,20];e['anchors']={'horizontal':'right','vertical':'bottom'}
        self.ui.transform(300,100);self.assertEqual(self.ui.pose(e)[:4],(175.,70.,20.,20.))
        self.assertEqual(self.ui.hit(285,80,300,100)['id'],'box');self.assertIsNone(self.ui.hit(185,80,300,100))
        self.click(285,80,300,100);self.assertEqual(self.ui.content.text(e),'Следующая реплика')
    def test_stretch_anchors_preserve_margins(self):
        e={'rect':[10,20,80,70],'anchors':{'horizontal':'stretch','vertical':'stretch'}}
        self.assertEqual(rect(e,(100,100),(300,200),(1,1,100,50)),(-90.,-30.,280.,170.))
        with self.assertRaises(ValueError):anchors({'horizontal':'oops'})
    def test_editor_settings_survive_reimport_and_replace_only_edited_fields(self):
        changes={'anchors':{'horizontal':'stretch','vertical':'bottom'},'dialogue':{'lines':['Первый','Второй']},'video':None}
        updated=apply_element(self.path,'1','box',changes);new=catalog();ne=new['slides'][0]['elements'][0]
        ne.update(id='fresh_id',name='New PowerPoint name',image='new.png',textSlot={'rect':[2,2,76,26],'image':'new_blank.png'})
        merged=merge_document(updated,new,[('1','box')]);e=merged['slides'][0]['elements'][0]
        self.assertEqual(e['id'],'box');self.assertEqual(e['image'],'new.png');self.assertEqual(e['textSlot']['image'],'new_blank.png')
        self.assertEqual(e['dialogue']['lines'],['Первый','Второй']);self.assertEqual(e['anchors']['vertical'],'bottom')
    def test_validation_and_assets_include_textless_image_and_video(self):
        data=catalog();e=data['slides'][0]['elements'][0];e['textSlot']['image']='blank.png';e['video']={'kind':'file','source':'media/a.mp4'}
        self.assertEqual(list(image_paths(data)),['blank.png']);self.assertEqual(list(media_paths(data)),['media/a.mp4'])
        for field,value in [('dialogue',{'lines':[]}),('text','x'*4097),('video',{'kind':'file','source':'../evil.mp4'}),('textStyle',{'size':float('nan')})]:
            broken=deepcopy(data);broken['slides'][0]['elements'][0][field]=value
            with self.assertRaises(ValueError):validate(broken)
    def test_text_job_never_blocks_render_thread(self):
        entered=threading.Event();release=threading.Event();cache=TextTextures(self.world)
        def slow(*args):entered.set();release.wait(2);return (1,1,b'\xff'*4)
        try:
            with patch('engine_ui_text.raster',side_effect=slow):
                cache.request('a',('Текст',20,10,{}));cache.pump();self.assertTrue(entered.wait(1))
                start=time.monotonic();cache.request('a',('Текст',20,10,{}));cache.pump();self.assertLess(time.monotonic()-start,.1)
                self.world.core.create_texture.assert_not_called();release.set()
                cache.pending['a'].result(timeout=1);cache.request('a',('Текст',20,10,{}));cache.pump()
                self.assertIn('a',cache.cache);self.world.core.create_texture.assert_called_once()
        finally:release.set();cache.close()
    def test_raster_unicode_has_transparent_background(self):
        w,h,data=raster('Привет, мир!',180,40,{'size':20,'color':[.2,.5,1,1]})
        self.assertEqual(len(data),w*h*4);self.assertIn(0,data[3::4]);self.assertGreater(max(data[3::4]),200)
        self.assertTrue(all(data[i]==51 for i in range(0,len(data),4)))
    def test_new_blueprint_actions_execute_real_runtime_methods(self):
        self.world.ui=self.ui;self.world.transactions=Mock()
        actions=['UIDialogueNext','UIDialogueReset','UISetText','UIStopVideo','DonationOpen','TransactionStart']
        for kind in actions:
            graph=click_graph('1','box',kind);source,_=generated_source(graph);env={};exec(source,env)
            obj=NS(world=self.world);env['_bp_ui_click'](obj,'1','box')
        self.assertEqual(self.ui.content.text(self.ui.slides['1']['elements'][0]),'Hello')
        self.world.transactions.donate.assert_called_once();self.world.transactions.start.assert_called_once_with('donation','donation')
    def test_blueprint_conditions_compile_and_invalid_status_rejected(self):
        for kind in ('UIDialogueFinished','TransactionIs','TransactionPaidOnce'):
            graph={'format':1,'nodes':[{'id':'1','type':'Update'},{'id':'2','type':kind},{'id':'3','type':'Branch'}],'links':[['1','next','3','in'],['2','value','3','condition']]}
            compile(Graph(graph).compile(),'<blueprint>','exec')
        graph['nodes'][1]={'id':'2','type':'TransactionIs','params':{'state':'fake'}}
        with self.assertRaises(ValueError):Graph(graph).compile()

class MediaTests(unittest.TestCase):
    def test_youtube_normalizes_links_without_fetching(self):
        for url in ['https://youtu.be/dQw4w9WgXcQ?t=30','https://www.youtube.com/watch?v=dQw4w9WgXcQ','https://youtube.com/embed/dQw4w9WgXcQ','https://youtube.com/shorts/dQw4w9WgXcQ']:
            self.assertEqual(youtube_url(url),'https://www.youtube.com/watch?v=dQw4w9WgXcQ')
        for url in ['https://youtube.com.evil.test/watch?v=dQw4w9WgXcQ','file:///a','http://youtu.be/dQw4w9WgXcQ','https://youtube.com/watch?v=oops']:
            with self.assertRaises(ValueError):youtube_url(url)
    def make_snapshot(self,path,external=False,target=None):
        from engine_pptx_media import P,A,R
        s=f'<p:sld xmlns:p="{P}" xmlns:a="{A}" xmlns:r="{R}"><p:cSld><p:spTree><p:pic><p:nvPicPr><p:cNvPr id="2" name="clip"/><p:nvPr><a:videoFile r:link="v"/></p:nvPr></p:nvPicPr></p:pic></p:spTree></p:cSld></p:sld>'
        rel=f'<Relationships><Relationship Id="v" Target="{target or "../media/clip.mp4"}"'+(' TargetMode="External"' if external else '')+'/></Relationships>'
        with zipfile.ZipFile(path,'w') as z:
            z.writestr('ppt/presentation.xml',f'<p:presentation xmlns:p="{P}" xmlns:r="{R}"><p:sldIdLst><p:sldId id="256" r:id="s"/></p:sldIdLst></p:presentation>')
            z.writestr('ppt/_rels/presentation.xml.rels','<Relationships><Relationship Id="s" Target="slides/slide1.xml"/></Relationships>')
            z.writestr('ppt/slides/slide1.xml',s);z.writestr('ppt/slides/_rels/slide1.xml.rels',rel)
            z.writestr('ppt/media/clip.mp4',b'embedded-video-test')
    def test_embedded_video_is_copied_to_ui_asset(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);path=root/'test.pptx';self.make_snapshot(path);data=catalog();enrich_media(path,data,root)
            v=data['slides'][0]['elements'][0]['video'];self.assertEqual(v['kind'],'file');self.assertFalse(v['autoplay'])
            self.assertEqual((root/v['source']).read_bytes(),b'embedded-video-test')
    def test_linked_youtube_becomes_video_link_and_local_external_not_read(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);path=root/'test.pptx';self.make_snapshot(path,True,'https://youtu.be/dQw4w9WgXcQ');data=catalog();enrich_media(path,data,root)
            self.assertEqual(data['slides'][0]['elements'][0]['video']['kind'],'youtube')
            self.make_snapshot(path,True,'file:///C:/private.mp4');data=catalog();enrich_media(path,data,root)
            self.assertNotIn('video',data['slides'][0]['elements'][0]);self.assertTrue(data['warnings'])
    def test_snapshot_rejects_escaping_zip_path(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'test.pptx';self.make_snapshot(p,target='../../../escape.mp4')
            with self.assertRaises(ValueError):enrich_media(p,catalog(),root)
    def test_video_player_visibility_geometry_and_no_wait_on_main_thread(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);ui=NS(enabled=True,active='1',loading=False,_transition=None,_viewport=(300,100),pose=lambda e:(175,10,20,30,0,1),transform=lambda w,h:(1,1,100,0),world=NS(log=Mock()))
            player=VideoPlayer(ui);player.folder=root;player.process=Mock();player.process.poll.return_value=None;player.started=time.monotonic()
            player.slide='1';player.element={'enabled':True};player.command={'playing':True};player.update()
            c=json.loads((root/'control.json').read_text());self.assertEqual(c['rect'],[275,10,20,30]);self.assertTrue(c['visible'])
            ui._transition={};ui._transition={'time':0};player.next_poll=0;player.update();self.assertFalse(json.loads((root/'control.json').read_text())['visible'])
            player.process.wait.assert_not_called()
    def test_youtube_uses_browser_and_editor_does_not_launch(self):
        ui=NS(world=NS(editor_mode=False,scripts_allowed=True));p=VideoPlayer(ui);e={'video':{'kind':'youtube','source':'https://youtu.be/dQw4w9WgXcQ'}}
        with patch('engine_ui_media.open_url') as browser:
            self.assertTrue(p.play('1',e));browser.assert_called_once()
            ui.world.editor_mode=True;self.assertFalse(p.play('1',e));self.assertEqual(browser.call_count,1)

class ReimportMediaTests(unittest.TestCase):
    def test_manual_video_and_dialogue_survive_actual_update_publish(self):
        import engine_pptx_import as importer
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);data=catalog();e=data['slides'][0]['elements'][0]
            e['video']={'kind':'file','source':'media/embedded.mp4'}
            def export(source,stage,engine,timeout,**options):
                (stage/'interface.ui.json').write_text(json.dumps(data))
                (stage/'_powerpoint_source.json').write_text(json.dumps({'directory':str(root),'source':str(root/'Deck.pptx')}))
                (stage/'media').mkdir();(stage/'media/embedded.mp4').write_bytes(b'new embedded bytes')
                return ''
            with patch.object(importer,'_run_export',side_effect=export):
                path,_=importer.import_powerpoint(None,root,'Menu')
                (path.parent/'media/custom.mp4').write_bytes(b'user selected video')
                apply_element(path,'1','box',{'video':{'kind':'file','source':'media/custom.mp4'},'anchors':{'vertical':'bottom'},'dialogue':{'lines':['Keep my line']}})
                importer.update_powerpoint(path.relative_to(root),root)
            result=json.loads(path.read_text());element=result['slides'][0]['elements'][0]
            self.assertEqual(element['dialogue']['lines'],['Keep my line'])
            self.assertEqual(element['video']['source'],'media/custom.mp4')
            self.assertEqual((path.parent/'media/custom.mp4').read_bytes(),b'user selected video')
            self.assertEqual(element['anchors']['vertical'],'bottom')
            self.assertFalse(list((root/'assets/ui').glob('.pptx-*')))

class PaymentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);root=Path(self.temp.name)
        (root/'payments.json').write_text(json.dumps({'donationUrl':'https://example.org/tip','checkoutApi':'https://example.org/api'}))
        self.pay=Transactions(root);self.addCleanup(self.pay.close)
    def finish_future(self,key='tip'):
        f=self.pay.records[key]['future']
        try:f.result(timeout=2)
        except Exception:pass
        self.pay.update()
    def test_link_is_not_paid_and_checkout_waits_for_confirmed_status(self):
        response={'product':'coffee','id':'a1','pollToken':'a'*20,'checkoutUrl':'https://example.org/pay/a1'}
        with patch('engine_transactions.open_url') as browser,patch('engine_transactions.request_json',return_value=response) as request:
            self.pay.donate();self.assertEqual(self.pay.state(),'idle')
            self.assertTrue(self.pay.start('coffee','tip'));self.assertFalse(self.pay.start('coffee','tip'))
            self.finish_future();self.assertEqual(self.pay.state('tip'),'pending');self.assertFalse(self.pay.paid_once('tip'))
            self.assertEqual(browser.call_count,2);self.assertEqual(request.call_count,1)
        with patch('engine_transactions.request_json',return_value={'product':'coffee','id':'a1','status':'succeeded'}):
            self.pay.records['tip']['next']=0;self.pay.update();self.finish_future()
        self.assertEqual(self.pay.state('tip'),'succeeded');self.assertTrue(self.pay.paid_once('tip'));self.assertFalse(self.pay.paid_once('tip'))
        self.pay.reset('tip');self.assertEqual(self.pay.state('tip'),'idle')
    def test_unknown_checkout_is_not_retried_or_reset(self):
        with patch('engine_transactions.request_json',side_effect=TimeoutError('network timeout')) as request:
            self.pay.start('coffee','tip');self.finish_future();self.assertEqual(self.pay.state('tip'),'unknown')
            self.assertFalse(self.pay.start('coffee','tip'));self.pay.update();self.assertEqual(request.call_count,1)
            with self.assertRaises(ValueError):self.pay.reset('tip')
    def test_mismatched_product_or_http_url_cannot_open_checkout(self):
        for response in [{'product':'wrong'}, {'product':'coffee','id':'a','pollToken':'t'*20,'checkoutUrl':'http://example.org/pay'}]:
            with patch('engine_transactions.request_json',return_value=response),patch('engine_transactions.open_url') as browser:
                key=str(len(self.pay.records));self.pay.start('coffee',key);self.finish_future(key);self.assertEqual(self.pay.state(key),'unknown');browser.assert_not_called()
    def test_slow_network_never_blocks_update(self):
        ready=threading.Event();release=threading.Event()
        def slow(*a):ready.set();release.wait(2);raise TimeoutError('fixture')
        with patch('engine_transactions.request_json',side_effect=slow):
            try:
                self.pay.start('coffee','tip');self.assertTrue(ready.wait(1))
                start=time.monotonic();self.pay.update();self.assertLess(time.monotonic()-start,.1);self.assertEqual(self.pay.state('tip'),'creating')
            finally:release.set()
    def test_close_while_request_finishes_does_not_open_browser(self):
        future=Future();self.pay.pool.shutdown(wait=False);self.pay.pool=Mock();self.pay.pool.submit.return_value=future
        with patch('engine_transactions.open_url') as browser:
            self.pay.start('coffee','tip');future.set_running_or_notify_cancel();self.pay.close()
            future.set_result({'product':'coffee','id':'a','pollToken':'x'*20,'checkoutUrl':'https://example.org/pay'});self.pay.update();browser.assert_not_called()

if __name__=='__main__':unittest.main()
