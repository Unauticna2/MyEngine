"""MagicaVoxel VOX reader; SIZE/XYZI/RGBA, PACK and static scene graph.

Format: https://github.com/ephtracy/voxel-model
Z-up MagicaVoxel -> Y-up engine: (x, y, z) -> (x, z, -y).
Animation uses the earliest frame; MATL shading is not a PBR material import.
"""
from pathlib import Path
import struct
import math


def default_palette():
    colors=[(0,0,0,0)]
    levels=(255,204,153,102,51,0)
    colors += [(r,g,b,255) for r in levels for g in levels for b in levels if (r,g,b)!=(0,0,0)]
    ramp=(238,221,187,170,136,119,85,68,34,17)
    colors += [(v,0,0,255) for v in ramp]+[(0,v,0,255) for v in ramp]
    colors += [(0,0,v,255) for v in ramp]+[(v,v,v,255) for v in ramp]
    assert len(colors)==256
    return colors


class Reader:
    def __init__(self,data):self.data=data;self.pos=0
    def take(self,n):
        if n<0 or self.pos+n>len(self.data):raise ValueError('Truncated VOX chunk')
        b=self.data[self.pos:self.pos+n];self.pos+=n;return b
    def int(self):return struct.unpack('<i',self.take(4))[0]
    def count(self,limit=100000):
        n=self.int()
        if not 0<=n<=limit:raise ValueError('Invalid VOX count')
        return n
    def string(self):return self.take(self.count(1024*1024)).decode('utf-8',errors='replace')
    def dictionary(self):
        d={}
        for _ in range(self.count(4096)):
            key=self.string();d[key]=self.string()
        return d


IDENTITY=((1,0,0),(0,1,0),(0,0,1))
def rotation(code):
    code=int(code);a=code&3;b=(code>>2)&3
    if a>2 or b>2 or a==b:raise ValueError('Invalid VOX rotation')
    axes=(a,b,3-a-b)
    return tuple(tuple((-1 if code&(1<<(r+4)) else 1) if c==axes[r] else 0 for c in range(3)) for r in range(3))
def mv(m,v):return tuple(sum(row[i]*v[i] for i in range(3)) for row in m)
def mm(a,b):return tuple(tuple(sum(a[r][k]*b[k][c] for k in range(3)) for c in range(3)) for r in range(3))


class VoxFile:
    def __init__(self,path):
        path=Path(path)
        if path.stat().st_size>128*1024*1024:raise ValueError('VOX file exceeds 128 MiB')
        b=path.read_bytes()
        if len(b)<20 or b[:4]!=b'VOX ':raise ValueError('Not a MagicaVoxel .vox file')
        self.version=struct.unpack_from('<I',b,4)[0]
        if not 150<=self.version<=200:raise ValueError(f'Unsupported VOX version {self.version}')
        self.models=[];self.palette=default_palette();self.nodes={};self.layers={};self.materials={}
        self._pending_size=None;self.pack=None
        tag,n,k=struct.unpack_from('<4sII',b,8)
        if tag!=b'MAIN' or n!=0 or 20+k!=len(b):raise ValueError('Invalid VOX MAIN extent')
        def walk(start,end,depth=0):
            if depth>32:raise ValueError('VOX chunk nesting too deep')
            while start<end:
                if end-start<12:raise ValueError('Truncated VOX header')
                tag,n,k=struct.unpack_from('<4sII',b,start);content=start+12;children=content+n;stop=children+k
                if stop>end:raise ValueError('VOX chunk extends past parent')
                self.chunk(tag,b[content:children])
                if k:walk(children,stop,depth+1)
                start=stop
        walk(20,len(b))
        if not self.models or self._pending_size is not None:raise ValueError('VOX has incomplete/missing SIZE/XYZI data')
        if self.pack is not None and self.pack!=len(self.models):raise ValueError('VOX PACK count differs from models')
    def chunk(self,tag,data):
        r=Reader(data)
        if tag==b'PACK':self.pack=r.count(4096)
        elif tag==b'SIZE':
            if self._pending_size is not None:raise ValueError('SIZE without XYZI')
            size=tuple(r.int() for _ in range(3))
            if len(data)!=12 or any(not 1<=n<=256 for n in size):raise ValueError('VOX dimensions must be 1..256')
            self._pending_size=size
        elif tag==b'XYZI':
            if self._pending_size is None:raise ValueError('XYZI without SIZE')
            n=r.count(256**3)
            if len(data)!=4+n*4:raise ValueError('Invalid XYZI byte count')
            cells=r.take(n*4);size=self._pending_size
            for i in range(0,len(cells),4):
                if any(cells[i+j]>=size[j] for j in range(3)):raise ValueError('VOX cell outside SIZE')
            self.models.append((size,cells));self._pending_size=None
        elif tag==b'RGBA':
            if len(data)!=1024:raise ValueError('RGBA must contain 256 colors')
            self.palette=[(0,0,0,0)]+[tuple(data[i:i+4]) for i in range(0,1020,4)]
        elif tag in (b'nTRN',b'nGRP',b'nSHP'):
            id=r.int();attrs=r.dictionary()
            if id in self.nodes:raise ValueError('Duplicate VOX scene node')
            if tag==b'nTRN':
                child=r.int();r.int();layer=r.int();n=r.count(10000)
                if not n:raise ValueError('Transform has no frames')
                frames=[r.dictionary() for _ in range(n)]
                frame=min(frames,key=lambda d:int(d.get('_f',0)))
                self.nodes[id]=('transform',attrs,child,layer,frame)
            elif tag==b'nGRP':self.nodes[id]=('group',attrs,[r.int() for _ in range(r.count())])
            else:
                n=r.count(4096)
                if not n:raise ValueError('Shape has no models')
                models=[(r.int(),r.dictionary()) for _ in range(n)]
                self.nodes[id]=('shape',attrs,min(models,key=lambda x:int(x[1].get('_f',0)))[0])
        elif tag==b'LAYR':
            id=r.int();self.layers[id]=r.dictionary();r.int()
        elif tag==b'MATL':
            id=r.int();self.materials[id]=r.dictionary()
        # Other chunks are length-delimited metadata, deliberately skipped.

    def grid(self,cell_size=.1,model_index=None):
        from engine_voxels import VoxelGrid
        if model_index is not None or not self.nodes:
            index=0 if model_index is None else int(model_index)
            if not 0<=index<len(self.models):raise ValueError('modelIndex outside VOX model list')
            size,cells=self.models[index];sx,sy,sz=size
            grid=VoxelGrid((sx,sz,sy),cell_size)
            for i in range(0,len(cells),4):
                x,y,z,c=cells[i:i+4]
                if c:grid.set(x,z,sy-1-y,self.palette[c])
        else:
            referenced=set()
            for node in self.nodes.values():
                if node[0]=='transform':referenced.add(node[2])
                elif node[0]=='group':referenced.update(node[2])
            roots=sorted(set(self.nodes)-referenced)
            if not roots:raise ValueError('Cyclic VOX scene')
            points={};visited=set();instances=0
            def visit(id,mat=IDENTITY,offset=(0,0,0),trail=()):
                nonlocal instances
                if id in trail or len(trail)>128:raise ValueError('Cyclic/deep VOX scene graph')
                if id not in self.nodes:raise ValueError('Missing VOX scene node')
                visited.add(id);node=self.nodes[id];kind,attrs=node[:2]
                if attrs.get('_hidden')=='1':return
                if kind=='transform':
                    _,_,child,layer,frame=node
                    if self.layers.get(layer,{}).get('_hidden')=='1' or frame.get('_hidden')=='1':return
                    rot=rotation(frame.get('_r',4));t=tuple(int(x) for x in frame.get('_t','0 0 0').split())
                    if len(t)!=3:raise ValueError('Invalid VOX translation')
                    tr=mv(mat,t);visit(child,mm(mat,rot),tuple(a+b for a,b in zip(offset,tr)),trail+(id,))
                elif kind=='group':
                    for child in node[2]:visit(child,mat,offset,trail+(id,))
                else:
                    index=node[2]
                    if not 0<=index<len(self.models):raise ValueError('Missing VOX model')
                    instances+=1
                    if instances>4096:raise ValueError('Too many VOX instances')
                    size,cells=self.models[index]
                    for i in range(0,len(cells),4):
                        x,y,z,c=cells[i:i+4]
                        if not c:continue
                        local=tuple(v+.5-(n//2) for v,n in zip((x,y,z),size))
                        q=tuple(a+b for a,b in zip(mv(mat,local),offset));q=(q[0],q[2],-q[1])
                        points[tuple(math.floor(v) for v in q)]=c
                        if len(points)>256**3:raise ValueError('Merged VOX exceeds cell budget')
            for id in roots:visit(id)
            if not points:raise ValueError('VOX scene has no visible cells')
            lo=tuple(min(p[k] for p in points) for k in range(3));hi=tuple(max(p[k] for p in points) for k in range(3))
            size=tuple(b-a+1 for a,b in zip(lo,hi))
            if max(size)>256:raise ValueError('Merged VOX scene exceeds 256 cells per axis; select a modelIndex')
            grid=VoxelGrid(size,cell_size)
            for p,c in points.items():grid.set(*(v-a for v,a in zip(p,lo)),self.palette[c])
        grid.revision=0
        return grid
