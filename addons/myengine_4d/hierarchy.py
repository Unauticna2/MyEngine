"""Hierarchy rules and output format, independent of Blender for validation."""
from collections import deque
import json
import math
import os
from pathlib import Path
import tempfile

MAX_LAYERS=256
MAX_BYTES=64*1024*1024

def group_layers(root,root_mode='AUTO'):
    if root is None:raise ValueError('Select the root object first')
    if root_mode not in ('AUTO','ROOT','CHILDREN'):raise ValueError('Unknown root mode')
    offset=1 if root_mode=='CHILDREN' or root_mode=='AUTO' and root.type=='EMPTY' else 0
    groups=[];queue=deque([(root,0)]);seen=set()
    while queue:
        obj,depth=queue.popleft();key=obj.as_pointer() if hasattr(obj,'as_pointer') else id(obj)
        if key in seen:raise ValueError('Cyclic object hierarchy')
        seen.add(key);layer=depth-offset
        if layer>=MAX_LAYERS:raise ValueError('Maximum 256 W layers')
        if layer>=0:
            while len(groups)<=layer:groups.append([])
            groups[layer].append(obj)
        for child in sorted(obj.children,key=lambda o:o.name):queue.append((child,depth+1))
    if not groups:raise ValueError('The selected container has no children')
    return groups

def header(spacing,root_mode):
    spacing=float(spacing)
    if not math.isfinite(spacing) or not 0<spacing<=1e6:raise ValueError('W spacing must be finite and positive')
    return '# myengine4d '+json.dumps({'format':1,'layerSpacing':spacing,'hierarchy':root_mode,'axes':'X,Z,-Y'},separators=(',',':'))+'\n'

class LimitedWriter:
    def __init__(self,file):self.file=file;self.size=0
    def write(self,text):
        self.size+=len(text.encode('utf-8'))
        if self.size>MAX_BYTES:raise ValueError('4D file exceeds the engine limit of 64 MiB')
        return self.file.write(text)

def atomic_export(path,write):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.'+path.name+'-',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as file:
            result=write(LimitedWriter(file));file.flush();os.fsync(file.fileno())
        os.replace(name,path);return result
    finally:
        if os.path.exists(name):os.unlink(name)
