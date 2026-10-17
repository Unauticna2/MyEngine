"""Native image parity, nonblocking uploads and scaled pointer coordinates."""
import ctypes as C
from concurrent.futures import ThreadPoolExecutor
import json,random,struct,tempfile,threading,time,unittest,zlib
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from engine_assets import decode_png,load_texture
from engine_ui_native import library,resize_rgba
from engine_ui import SlideUI
from engine_ui_scaling import normalized,transform,clip_rect
from engine_runtime import Resources
from engine_ui_assets import UIAssets
from PNGJSONUnitylity import chunk,SIGNATURE


def png_fixture(color,mode,w=17,h=7):
    rng=random.Random(300+color);channels={0:1,2:3,3:1,4:2,6:4}[color]
    original=bytes(rng.randrange(16 if color==3 else 256) for _ in range(w*h*channels));stride=w*channels
    raw=bytearray();previous=bytes(stride)
    for y in range(h):
        row=original[y*stride:(y+1)*stride];raw.append(mode)
        for x,value in enumerate(row):
            a=row[x-channels] if x>=channels else 0;b=previous[x];c=previous[x-channels] if x>=channels else 0
            p=a+b-c;dist=[abs(p-a),abs(p-b),abs(p-c)];paeth=[a,b,c][dist.index(min(dist))]
            pred=[0,a,b,(a+b)//2,paeth][mode];raw.append((value-pred)&255)
        previous=row
    header=struct.pack('>IIBBBBB',w,h,8,color,0,0,0)
    palette=bytes(rng.randrange(256) for _ in range(48))
    extras=chunk(b'PLTE',palette)+chunk(b'tRNS',bytes(range(16))) if color==3 else chunk(b'tRNS',b'\0'+original[:1]) if color==0 else chunk(b'tRNS',b''.join(b'\0'+bytes([v]) for v in original[:3])) if color==2 else b''
    return SIGNATURE+chunk(b'IHDR',header)+extras+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')

class NativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if library() is None:raise unittest.SkipTest('Compile MyEngineUI native library first')
    def test_all_filters_color_types_transparency_and_orientation(self):
        from PIL import Image
        import io
        for color in (0,2,3,4,6):
            for mode in range(5):
                with self.subTest(color=color,filter=mode):
                    png=png_fixture(color,mode);native=decode_png(png)
                    expected=Image.open(io.BytesIO(png)).convert('RGBA').transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes()
                    self.assertEqual(native[2],expected)
                    with patch('engine_ui_native.library',return_value=None):self.assertEqual(native,decode_png(png))
    def test_native_resize_matches_previous_floor_sampling(self):
        source=bytes(range(3*5*4));result=resize_rgba(source,3,5,4,8)
        expected=b''.join(source[((y*5//8)*3+x*3//4)*4:((y*5//8)*3+x*3//4)*4+4] for y in range(8) for x in range(4))
        self.assertEqual(result,expected)
    def test_abi_rejects_bad_lengths_and_filter_without_overwrite(self):
        dll=library();buf=(C.c_ubyte*12)(*([123]*12))
        args=[b'\0\1\2\3\4',5,1,1,6,b'',0,b'',0,C.byref(buf,4),4]
        args[1]=4;self.assertEqual(dll.MEUI_PngPixels(*args),1);self.assertEqual(bytes(buf),bytes([123]*12))
        args[1]=5;args[0]=b'\5\1\2\3\4';self.assertEqual(dll.MEUI_PngPixels(*args),2)
        self.assertEqual(bytes(buf),bytes([123]*12))
        args[0]=b'\0\1\2\3\4';self.assertEqual(dll.MEUI_PngPixels(*args),0)
        self.assertEqual(bytes(buf),bytes([123]*4+[1,2,3,4]+[123]*4))
    def test_native_concurrent_calls_have_no_shared_pixel_state(self):
        blobs=[png_fixture(c,m,128,64) for c in (0,2,3,4,6) for m in (1,4)]
        expected=[decode_png(b) for b in blobs]
        with ThreadPoolExecutor(max_workers=4) as pool:self.assertEqual(list(pool.map(decode_png,blobs)),expected)

class ScaleTests(unittest.TestCase):
    def test_modes_and_logarithmic_width_height_match(self):
        for mode,expected in [('fit',(1.,1.,50.,0.)),('fill',(2.,2.,0.,-50.)),('stretch',(2.,1.,0.,0.)),('width',(2.,2.,0.,-50.)),('height',(1.,1.,50.,0.))]:
            self.assertEqual(transform(100,100,200,100,normalized({'mode':mode})),expected)
        self.assertAlmostEqual(transform(100,100,200,100,normalized({'mode':'match','match':.5}))[0],2**.5)
        self.assertEqual(clip_rect(100,100,200,100,transform(100,100,200,100,normalized({'mode':'fill'}))),(0,0,200,100))
        for bad in [{'mode':'bad'},{'match':float('nan')},{'match':2}]:
            with self.assertRaises(ValueError):normalized(bad)
    def test_rotated_button_hit_uses_the_same_stretched_coordinates(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);data={'format':1,'kind':'MyEngine.UI','width':100,'height':100,'startSlide':'1','slides':[
                {'id':'1','elements':[{'id':'go','rect':[35,35,30,30],'rotation':35,'onClick':[{'action':'next'}]}]},
                {'id':'2','elements':[]}]};(root/'ui.json').write_text(json.dumps(data))
            ui=SlideUI(NS(root=root,ui_scale={'mode':'stretch'}),'ui.json')
            self.assertEqual(ui.hit(150,50,300,100)['id'],'go')
            self.assertIsNone(ui.hit(30,50,300,100));self.assertIsNone(ui.hit(-1,50,300,100))
            ui.update(0,(150,50,True,300,100));ui.update(0,(150,50,False,300,100));self.assertEqual(ui.active,'2')

class AsyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.owner=threading.get_ident();self.upload_threads=[];self.logs=[]
        def create(image):self.upload_threads.append(threading.get_ident());return len(self.upload_threads)
        self.core=NS(create_texture=create,delete_texture=lambda t:None)
        self.resources=Resources(self.core,self.root);self.world=NS(root=self.root,resources=self.resources,log=lambda *a:self.logs.append(a))
        self.assets=UIAssets(self.world)
        self.addCleanup(self.shutdown)
        for i in range(8):(self.root/f'{i}.png').write_bytes(png_fixture(6,0,2,2))
    def shutdown(self):self.assets.close();self.resources.close();self.core.resource_cache.close()
    def settle(self,assets,names):
        end=time.monotonic()+5
        while not assets.ready(names) and time.monotonic()<end:assets.pump();time.sleep(.001)
        self.assertTrue(assets.ready(names))
    def test_slow_decode_never_blocks_pump_and_uploads_only_on_owner_thread(self):
        release=threading.Event();started=threading.Event();self.addCleanup(release.set)
        def slow(path):started.set();release.wait(2);return (1,1,b'\xff'*4)
        with patch('engine_ui_assets.load_texture',side_effect=slow):
            names=[f'{i}.png' for i in range(8)];self.assets.request(names);self.assets.pump();self.assertTrue(started.wait(1))
            start=time.perf_counter()
            for _ in range(50):self.assets.pump()
            self.assertLess(time.perf_counter()-start,.15);self.assertLessEqual(len(self.assets.pending),4)
            self.assertEqual(self.upload_threads,[]);release.set();self.settle(self.assets,names)
        self.assertEqual(self.upload_threads,[self.owner]*8)
    def test_repeated_slide_and_world_use_cache_without_decoding(self):
        names=['0.png','1.png'];self.assets.request(names);self.settle(self.assets,names)
        self.assets.close();self.resources.close();resources=Resources(self.core,self.root)
        other=UIAssets(NS(resources=resources,log=lambda *a:None))
        try:
            with patch('engine_ui_assets.load_texture',side_effect=AssertionError('warm image decoded')):
                other.request(names);self.settle(other,names)
            self.assertEqual(len(self.upload_threads),2)
        finally:other.close();resources.close()
    def test_corrupt_image_reported_once_without_permanent_loading(self):
        (self.root/'0.png').write_bytes(b'bad PNG');self.assets.request(['0.png']);self.settle(self.assets,['0.png'])
        for _ in range(3):self.assets.pump()
        self.assertIn('0.png',self.assets.failed);self.assertEqual(len(self.logs),1)
    def test_slide_waits_for_images_before_starting_transition(self):
        data={'format':1,'kind':'MyEngine.UI','width':100,'height':100,'startSlide':'1','slides':[
            {'id':str(i+1),'elements':[{'id':'go','rect':[0,0,100,100],'image':f'{i}.png','onClick':[{'action':'next'}]}]} for i in range(2)]}
        (self.root/'ui.json').write_text(json.dumps(data));ui=SlideUI(self.world,'ui.json');self.addCleanup(ui.close)
        self.assertTrue(ui.loading);self.assertIsNone(ui.hit(50,50,100,100))
        self.settle(ui.assets,ui.slide_images('1'));ui.update(0)
        ui.assets.handles.pop('1.png',None);ui.assets.known.discard('1.png');ui.assets.pending.pop('1.png',None)
        ui.show_slide('2',transition='fade',duration=1)
        self.assertEqual(ui.active,'1');self.assertTrue(ui.loading)
        ui.update(.05);self.assertIsNone(ui._transition)
        self.settle(ui.assets,ui.slide_images('2'));ui.update(.05)
        self.assertEqual(ui.active,'2');self.assertIsNotNone(ui._transition);self.assertEqual(ui._transition['time'],0)

if __name__=='__main__':unittest.main()
