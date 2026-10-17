"""Optional, versioned C ABI for PNG pixels. ctypes.CDLL releases the GIL."""
from pathlib import Path
import ctypes as C
import os,sys,threading
_lock=threading.Lock();_library=None;_tried=False;_error=None

def library():
    global _library,_tried,_error
    if _tried:return _library
    with _lock:
        if _tried:return _library
        root=Path(__file__).resolve().parent
        path=Path(os.environ.get('MYENGINE_UI_DLL') or (root/'MyEngineUI.dll' if sys.platform=='win32' else root/'platforms/linux/libMyEngineUI.so'))
        try:
            if path.is_file():
                dll=C.CDLL(str(path));dll.MEUI_Version.argtypes=[];dll.MEUI_Version.restype=C.c_uint32
                if dll.MEUI_Version()!=1:raise ValueError('Unsupported MyEngineUI ABI')
                dll.MEUI_PngPixels.argtypes=[C.c_void_p,C.c_uint64,C.c_uint32,C.c_uint32,C.c_uint32,C.c_void_p,C.c_uint32,C.c_void_p,C.c_uint32,C.c_void_p,C.c_uint64]
                dll.MEUI_PngPixels.restype=C.c_int
                dll.MEUI_ResizeRGBA.argtypes=[C.c_void_p,C.c_uint64,C.c_uint32,C.c_uint32,C.c_void_p,C.c_uint64,C.c_uint32,C.c_uint32]
                dll.MEUI_ResizeRGBA.restype=C.c_int;_library=dll
        except (OSError,AttributeError,ValueError) as ex:_error=str(ex)
        _tried=True
    return _library

def status():
    return 'C++ MyEngineUI ABI 1' if library() is not None else 'Python fallback'+(': '+_error if _error else ' (MyEngineUI library not installed)')

def png_pixels(raw,w,h,color,palette,alpha):
    dll=library()
    if dll is None:return None
    result=bytearray(w*h*4);buf=(C.c_ubyte*len(result)).from_buffer(result)
    code=dll.MEUI_PngPixels(raw,len(raw),w,h,color,palette,len(palette),alpha,len(alpha),buf,len(result))
    if code:raise ValueError('Native PNG pixel conversion failed (code '+str(code)+')')
    return bytes(result)

def resize_rgba(pixels,w,h,nw,nh):
    dll=library()
    if dll is None:return None
    result=bytearray(nw*nh*4);buf=(C.c_ubyte*len(result)).from_buffer(result)
    code=dll.MEUI_ResizeRGBA(pixels,len(pixels),w,h,buf,len(result),nw,nh)
    if code:raise ValueError('Native texture resize failed (code '+str(code)+')')
    return bytes(result)
