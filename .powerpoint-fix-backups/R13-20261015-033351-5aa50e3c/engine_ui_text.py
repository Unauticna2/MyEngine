"""Worker-side Unicode text rasterization. GDI on Windows, Pillow on Linux."""
import ctypes as C
import math
import sys
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor


def style(value=None):
    v=value or {};size=float(v.get('size',24));color=list(v.get('color',[1,1,1,1]));align=v.get('align','left')
    if not math.isfinite(size) or not 4<=size<=200:raise ValueError('Text size must be 4..200')
    if len(color) not in (3,4) or any(not math.isfinite(float(x)) or not 0<=float(x)<=1 for x in color):raise ValueError('Text color must be RGB(A) 0..1')
    if len(color)==3:color.append(1.)
    if align not in ('left','center','right'):raise ValueError('Text alignment must be left/center/right')
    return {'font':str(v.get('font','Segoe UI'))[:100],'size':size,'color':color,'bold':bool(v.get('bold',False)),'align':align}


def raster(text,width,height,settings):
    """Returns bottom-first RGBA. Runs in a worker; no GL or shared DC."""
    settings=style(settings);scale=min(2.,2048/max(1,width),1024/max(1,height))
    w=max(1,math.ceil(width*scale));h=max(1,math.ceil(height*scale));size=max(4,round(settings['size']*scale))
    mask=_gdi(text,w,h,size,settings) if sys.platform=='win32' else _pillow(text,w,h,size,settings)
    rgb=bytes(round(float(v)*255) for v in settings['color'][:3]);opacity=settings['color'][3]
    data=bytearray(w*h*4);data[0::4]=rgb[:1]*(w*h);data[1::4]=rgb[1:2]*(w*h);data[2::4]=rgb[2:]*(w*h)
    data[3::4]=bytes(round(a*opacity) for a in mask)
    return w,h,bytes(data)


def _gdi(text,w,h,size,settings):
    class Rect(C.Structure):_fields_=[('left',C.c_int32),('top',C.c_int32),('right',C.c_int32),('bottom',C.c_int32)]
    class Header(C.Structure):
        _fields_=[('size',C.c_uint32),('width',C.c_int32),('height',C.c_int32),('planes',C.c_uint16),('bits',C.c_uint16),('compression',C.c_uint32),('image',C.c_uint32),('xppm',C.c_int32),('yppm',C.c_int32),('used',C.c_uint32),('important',C.c_uint32)]
    g=C.WinDLL('gdi32',use_last_error=True);u=C.WinDLL('user32',use_last_error=True);P=C.c_void_p;I=C.c_int;U=C.c_uint32
    def bind(d,n,r,*a):f=getattr(d,n);f.restype=r;f.argtypes=list(a);return f
    dc=bind(g,'CreateCompatibleDC',P,P)(None);bitmap=None;old_bitmap=None;font=None;old_font=None
    if not dc:raise C.WinError(C.get_last_error())
    select=bind(g,'SelectObject',P,P,P);delete=bind(g,'DeleteObject',I,P)
    draw=bind(u,'DrawTextW',I,P,C.c_wchar_p,I,C.POINTER(Rect),U)
    create_font=bind(g,'CreateFontW',P,I,I,I,I,I,U,U,U,U,U,U,U,U,C.c_wchar_p)
    flags=0x10|0x800|{'left':0,'center':1,'right':2}[settings['align']]
    try:
        header=Header(40,w,h,1,32,0,w*h*4,0,0,0,0);bits=P()
        bitmap=bind(g,'CreateDIBSection',P,P,P,U,C.POINTER(P),P,U)(dc,C.byref(header),0,C.byref(bits),None,0)
        if not bitmap or not bits.value:raise C.WinError(C.get_last_error())
        old_bitmap=select(dc,bitmap);C.memset(bits,0,w*h*4)
        bind(g,'SetBkMode',I,P,I)(dc,1);bind(g,'SetTextColor',U,P,U)(dc,0xffffff)
        # Fit text down to a readable minimum; the rectangle clips any excess.
        while True:
            font=create_font(-size,0,0,0,700 if settings['bold'] else 400,0,0,0,1,0,0,4,0,settings['font'])
            if not font:raise C.WinError(C.get_last_error())
            prev=select(dc,font)
            if old_font is None:old_font=prev
            measure=Rect(0,0,w,h);draw(dc,text,-1,C.byref(measure),flags|0x400)
            if measure.bottom<=h and measure.right<=w or size<=8:break
            select(dc,old_font);delete(font);font=None;size=max(8,size-2)
        box=Rect(0,0,w,h);draw(dc,text,-1,C.byref(box),flags)
        bind(g,'GdiFlush',I)()
        return C.string_at(bits,w*h*4)[0::4]
    finally:
        if old_font:select(dc,old_font)
        if font:delete(font)
        if old_bitmap:select(dc,old_bitmap)
        if bitmap:delete(bitmap)
        bind(g,'DeleteDC',I,P)(dc)


def _pillow(text,w,h,size,settings):
    from PIL import Image,ImageDraw,ImageFont
    from pathlib import Path
    fontfile=Path('/usr/share/fonts/truetype/dejavu/DejaVuSans'+('-Bold' if settings['bold'] else '')+'.ttf')
    while True:
        font=ImageFont.truetype(str(fontfile),size);lines=[]
        for paragraph in text.split('\n'):
            line=''
            for char in paragraph:
                if line and font.getlength(line+char)>w:lines.append(line);line=''
                line+=char
            lines.append(line)
        step=sum(font.getmetrics())
        if len(lines)*step<=h or size<=8:break
        size=max(8,size-2)
    image=Image.new('L',(w,h));draw=ImageDraw.Draw(image)
    for i,line in enumerate(lines):
        length=font.getlength(line);x=0 if settings['align']=='left' else (w-length)/2 if settings['align']=='center' else w-length
        draw.text((x,i*step),line,font=font,fill=255)
    return image.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes()


class TextTextures:
    """Two worker jobs maximum, one upload/frame, 32 MiB GPU cache."""
    def __init__(self,world):
        self.world=world;self.pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='ui-text')
        self.pending={};self.cache=OrderedDict();self.failed=set();self.wanted={};self.closed=False
    def request(self,key,args):self.wanted[key]=args
    def pump(self):
        if self.closed:return
        uploaded=False
        for key,future in list(self.pending.items()):
            if not future.done():continue
            if key not in self.wanted:del self.pending[key];continue
            if uploaded:continue
            del self.pending[key]
            try:
                image=future.result();handle=self.world.core.create_texture(image)
                self.cache[key]=(handle,len(image[2]));uploaded=True
            except Exception as ex:self.failed.add(key);self.world.log('UI TEXT: '+str(ex))
        for key,args in self.wanted.items():
            if key in self.cache:self.cache.move_to_end(key)
            elif key not in self.pending and key not in self.failed and len(self.pending)<2:self.pending[key]=self.pool.submit(raster,*args)
        while sum(v[1] for v in self.cache.values())>32*1024*1024:
            old=next((k for k in self.cache if k not in self.wanted),None)
            if old is None:break
            handle,_=self.cache.pop(old);self.world.core.delete_texture(handle)
        self.wanted={}
    def close(self):
        self.closed=True
        for f in self.pending.values():f.cancel()
        self.pool.shutdown(wait=False,cancel_futures=True)
        for handle,_ in self.cache.values():self.world.core.delete_texture(handle)
        self.cache.clear();self.pending.clear();self.wanted.clear()
