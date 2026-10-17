"""Native C++ slice kernel. Handles are cached; GL uploads stay on the render owner."""
from pathlib import Path
from collections import OrderedDict
from array import array
import ctypes as C,os,threading
from engine_assets import MeshData

class NativeSlicer:
 def __init__(self,path):
  self.dll=C.CDLL(str(path));self.lock=threading.Lock();self.sources=OrderedDict()
  specs={'Slice4DCreate':([C.c_void_p,C.c_void_p,C.c_uint32],C.c_void_p),'Slice4DDestroy':([C.c_void_p],None),'Slice4DCompute':([C.c_void_p,C.c_double,C.c_double,C.c_void_p,C.c_void_p,C.c_double],C.c_void_p),'Slice4DData':([C.c_void_p],C.c_void_p),'Slice4DCount':([C.c_void_p],C.c_uint32),'Slice4DFree':([C.c_void_p],None),'Slice4DError':([],C.c_char_p)}
  for n,(args,result) in specs.items():f=getattr(self.dll,n);f.argtypes=args;f.restype=result
 def slice(self,layers,spacing,sw,angles,scale,cut):
  with self.lock:
   key=tuple(id(l.geometry) for l in layers)
   if key not in self.sources:
    vertices=array('f');counts=(C.c_uint32*len(layers))(*(len(l.geometry.vertices)//8 for l in layers))
    for l in layers:vertices.extend(l.geometry.vertices)
    raw=(C.c_float*len(vertices)).from_buffer(vertices);handle=self.dll.Slice4DCreate(raw,counts,len(layers))
    if not handle:raise ValueError(self.dll.Slice4DError().decode())
    self.sources[key]=(handle,tuple(l.geometry for l in layers))
    while len(self.sources)>8:self.dll.Slice4DDestroy(self.sources.popitem(last=False)[1][0])
   self.sources.move_to_end(key);handle=self.sources[key][0]
   result=self.dll.Slice4DCompute(handle,spacing,sw,(C.c_double*3)(*angles),(C.c_double*3)(*scale),cut)
   if not result:raise ValueError(self.dll.Slice4DError().decode())
   try:
    count=self.dll.Slice4DCount(result)
    if not count:return None
    output=array('f');output.frombytes(C.string_at(self.dll.Slice4DData(result),count*4))
    return MeshData(output,tuple(min(output[k::8]) for k in range(3)),tuple(max(output[k::8]) for k in range(3)))
   finally:self.dll.Slice4DFree(result)
 def close(self):
  with self.lock:
   for handle,_ in self.sources.values():self.dll.Slice4DDestroy(handle)
   self.sources.clear()

_backend=None;_checked=False;_warned=False
def backend():
 global _backend,_checked
 if not _checked:
  _checked=True;path=Path(os.environ.get('MYENGINE_SLICE_DLL',Path(__file__).parent/'Slice4D.dll'))
  if path.is_file():_backend=NativeSlicer(path)
 return _backend

def slice_layers(layers,spacing,sw,angles,scale,cut):
 global _warned
 native=backend()
 if native:return native.slice(layers,spacing,sw,angles,scale,cut)
 if not _warned:
  _warned=True;print('4D: Slice4D.dll is missing; using the slower Python fallback. Run build.cmd for native acceleration.',flush=True)
 from engine_four_d import slice_layers as python_slice
 return python_slice(layers,spacing,sw,angles,scale,cut)
