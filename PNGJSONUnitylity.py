"""Screenshot PNG + UTF-8 JSON in an ordinary iTXt chunk. Never pickle or eval."""
from dataclasses import asdict,is_dataclass,fields
from pathlib import Path
import json,struct,zlib,os,tempfile

SIGNATURE=b'\x89PNG\r\n\x1a\n';KEY=b'MyEngine.Save';LIMIT=8*1024*1024;PNG_LIMIT=128*1024*1024

def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)

def chunks(png):
    if len(png)>PNG_LIMIT or not png.startswith(SIGNATURE):raise ValueError('Invalid or oversized PNG')
    at=8;first=True;ended=False
    while at+12<=len(png):
        n=struct.unpack_from('>I',png,at)[0];end=at+n+12
        if end>len(png):raise ValueError('Truncated PNG chunk')
        kind=png[at+4:at+8];data=png[at+8:at+8+n]
        if first and (kind!=b'IHDR' or n!=13):raise ValueError('Missing PNG header')
        first=False
        if zlib.crc32(kind+data)&0xffffffff!=struct.unpack_from('>I',png,end-4)[0]:raise ValueError('PNG CRC mismatch')
        yield kind,data
        at=end
        if kind==b'IEND':
            if n or at!=len(png):raise ValueError('Invalid PNG end')
            ended=True;break
    if not ended:raise ValueError('Missing PNG end')

def encode_rgba(width,height,rgba):
    if not 1<=width<=16384 or not 1<=height<=16384 or len(rgba)!=width*height*4:raise ValueError('Invalid screenshot dimensions')
    scan=b''.join(b'\x00'+rgba[y*width*4:(y+1)*width*4] for y in range(height))
    return SIGNATURE+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(scan,3))+chunk(b'IEND',b'')

def capture_rgba():
    """Current GL framebuffer; call from a queued end-of-frame screenshot."""
    import ctypes as C
    from engine_gl import GL,I,U,P
    gl=GL();viewport=(I*4)();gl.fn('glGetIntegerv',None,U,P)(0x0BA2,viewport);x,y,w,h=viewport
    if not 0<w<=16384 or not 0<h<=16384 or w*h*4>PNG_LIMIT:raise ValueError('Invalid/oversized viewport')
    raw=(C.c_ubyte*(w*h*4))();old=I();gl.fn('glGetIntegerv',None,U,P)(0x0D05,C.byref(old))
    try:
        gl.fn('glPixelStorei',None,U,I)(0x0D05,1);gl.fn('glReadPixels',None,I,I,I,I,U,U,P)(x,y,w,h,0x1908,0x1401,raw)
        if gl.fn('glGetError',U)():raise RuntimeError('Screenshot read failed')
    finally:gl.fn('glPixelStorei',None,U,I)(0x0D05,old.value)
    data=bytes(raw);return w,h,b''.join(data[row*w*4:(row+1)*w*4] for row in range(h-1,-1,-1))

def capture_png():return encode_rgba(*capture_rgba())

def json_data(value):
    if is_dataclass(value) and not isinstance(value,type):return asdict(value)
    if isinstance(value,(dict,list,str,int,float,bool)) or value is None:return value
    if hasattr(value,'__dict__'):return {k:v for k,v in vars(value).items() if not k.startswith('_')}
    raise TypeError('Save a dataclass, plain data object or JSON value')

def with_json(png,value):
    envelope={'format':'MyEngine.PNGJSON','version':1,'data':json_data(value)}
    text=json.dumps(envelope,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')
    if len(text)>LIMIT:raise ValueError('Save JSON exceeds 8 MiB')
    result=bytearray(SIGNATURE)
    for kind,data in chunks(png):
        if kind==b'iTXt' and data.split(b'\x00',1)[0]==KEY:continue
        if kind==b'IEND':result.extend(chunk(b'iTXt',KEY+b'\x00\x00\x00\x00\x00'+text))
        result.extend(chunk(kind,data))
    return bytes(result)

def read_json(png):
    result=None
    for kind,data in chunks(png):
        if kind!=b'iTXt' or data.split(b'\x00',1)[0]!=KEY:continue
        if result is not None:raise ValueError('Duplicate save data')
        rest=data[len(KEY)+1:]
        if len(rest)<4:raise ValueError('Invalid save chunk')
        compressed,method=rest[:2];parts=rest[2:].split(b'\x00',2)
        if len(parts)!=3 or compressed not in (0,1) or method!=0:raise ValueError('Invalid iTXt save')
        text=parts[2]
        if compressed:
            d=zlib.decompressobj();text=d.decompress(text,LIMIT+1)
            if not d.eof or d.unused_data or len(text)>LIMIT:raise ValueError('Invalid/oversized compressed save')
        if len(text)>LIMIT:raise ValueError('Save JSON exceeds 8 MiB')
        result=json.loads(text.decode('utf-8'),parse_constant=lambda x:(_ for _ in ()).throw(ValueError(x)))
        if not isinstance(result,dict) or 'data' not in result or result.get('format')!='MyEngine.PNGJSON' or result.get('version')!=1:raise ValueError('Unsupported save version')
    if result is None:raise ValueError('This PNG contains no MyEngine save')
    return result['data']

def atomic_write(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);fd,tmp=tempfile.mkstemp(prefix=path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

class PNGJSONUnitylity:
    @staticmethod
    def ToPngJson(path,data,png=None):
        if png is None:
            import engine_runtime
            if engine_runtime._world is not None:return engine_runtime._world.save_png(path,data)
        encoded=with_json(capture_png() if png is None else bytes(png),data);atomic_write(path,encoded);return Path(path)
    @staticmethod
    def FromPngJson(path,cls=None):
        path=Path(path)
        if path.stat().st_size>PNG_LIMIT:raise ValueError('PNG is too large')
        data=read_json(path.read_bytes())
        if cls is None:return data
        if not isinstance(data,dict):raise ValueError('Class data must be a JSON object')
        if is_dataclass(cls):return cls(**data)
        result=cls();names=set(vars(result))|set(getattr(cls,'__annotations__',{}))
        if set(data)-names:raise ValueError('Save contains fields outside the requested class')
        for key,value in data.items():setattr(result,key,value)
        return result

ToPngJson=PNGJSONUnitylity.ToPngJson
FromPngJson=PNGJSONUnitylity.FromPngJson
