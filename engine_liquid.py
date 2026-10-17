"""Height-field liquid ECS component + bounded asynchronous system.
Only worker-owned numeric arrays cross the simulation boundary; GL stays on the owner.
"""
from array import array
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
import ctypes as C
import math
import os
import sys
from engine_assets import MeshData

def settings(value=None):
    value={} if value is None else value
    if not isinstance(value,dict):raise ValueError('Liquid settings must be an object')
    out={}
    for key,default,low,high in [('nx',32,2,128),('nz',32,2,128)]:
        v=value.get(key,default)
        if type(v) is not int or not low<=v<=high:raise ValueError(f'Liquid {key}: {low}..{high}')
        out[key]=v
    for key,default,low,high in [('cellSize',.25,.02,10),('depth',.6,0,20),('gravity',9.81,0,100),('damping',1.5,0,50),('updateHz',20,10,60)]:
        v=float(value.get(key,default))
        if not math.isfinite(v) or not low<=v<=high:raise ValueError(f'Liquid {key}: {low}..{high}')
        out[key]=v
    count=out['nx']*out['nz']
    bed=value.get('bed',[0.0]*count);solid=value.get('solid',[False]*count)
    if not isinstance(bed,list) or len(bed)!=count or any(not isinstance(x,(int,float)) or not math.isfinite(x) or abs(x)>100 for x in bed):raise ValueError('Liquid bed must have nx*nz finite heights')
    if not isinstance(solid,list) or len(solid)!=count or any(type(x) is not bool for x in solid):raise ValueError('Liquid solid must have nx*nz booleans')
    out['bed']=list(bed);out['solid']=list(solid)
    return out

class State:
    def __init__(self,config):
        self.config=settings(config);c=self.config;self.nx=c['nx'];self.nz=c['nz'];n=self.nx*self.nz
        self.h=array('d',[c['depth'] if not c['solid'][i] else 0 for i in range(n)])
        self.bed=array('d',c['bed']);self.solid=array('B',c['solid'])
        self.qx=array('d',[0])*((self.nx-1)*self.nz);self.qz=array('d',[0])*(self.nx*(self.nz-1));self.factor=array('d',[0])*n
    def volume(self):return sum(self.h)*self.config['cellSize']**2
    def command(self,kind,x,z,amount,radius):
        c=self.config;cell=c['cellSize'];nx,nz=self.nx,self.nz
        if kind=='water':
            weights=[]
            for iz in range(nz):
                for ix in range(nx):
                    i=iz*nx+ix;dx=(ix+.5-nx*.5)*cell-x;dz=(iz+.5-nz*.5)*cell-z
                    d=math.hypot(dx,dz)
                    if not self.solid[i] and d<=radius:weights.append((i,max(.001,1-d/radius)))
            total=sum(w for _,w in weights)
            for i,w in weights:self.h[i]+=amount*w/total/cell**2
        else:
            # Radial velocity impulse moves existing water; it creates no extra volume.
            for iz in range(nz):
                for ix in range(nx-1):
                    dx=(ix+1-nx*.5)*cell-x;dz=(iz+.5-nz*.5)*cell-z;d=math.hypot(dx,dz)
                    if 1e-9<d<radius:self.qx[iz*(nx-1)+ix]+=amount*dx/d*(1-d/radius)*cell**2
            for iz in range(nz-1):
                for ix in range(nx):
                    dx=(ix+.5-nx*.5)*cell-x;dz=(iz+1-nz*.5)*cell-z;d=math.hypot(dx,dz)
                    if 1e-9<d<radius:self.qz[iz*nx+ix]+=amount*dz/d*(1-d/radius)*cell**2

def python_step(s,dt):
    nx,nz=s.nx,s.nz;h,bed,solid,qx,qz=s.h,s.bed,s.solid,s.qx,s.qz;c=s.config;area=c['cellSize']**2;drag=math.exp(-c['damping']*dt)
    for z in range(nz):
        for x in range(nx-1):
            a=z*nx+x;b=a+1;f=z*(nx-1)+x
            if solid[a] or solid[b]:qx[f]=0;continue
            sa,sb=bed[a]+h[a],bed[b]+h[b];wet=max(0,max(sa,sb)-max(bed[a],bed[b]))
            qx[f]=0 if wet<=1e-12 else (qx[f]+dt*c['gravity']*wet*(sa-sb))*drag
    for z in range(nz-1):
        for x in range(nx):
            a=z*nx+x;b=a+nx;f=z*nx+x
            if solid[a] or solid[b]:qz[f]=0;continue
            sa,sb=bed[a]+h[a],bed[b]+h[b];wet=max(0,max(sa,sb)-max(bed[a],bed[b]))
            qz[f]=0 if wet<=1e-12 else (qz[f]+dt*c['gravity']*wet*(sa-sb))*drag
    out=[0.0]*len(h)
    faces=[(z*nx+x,z*nx+x+1,qx,z*(nx-1)+x) for z in range(nz) for x in range(nx-1)]
    faces.extend((z*nx+x,(z+1)*nx+x,qz,z*nx+x) for z in range(nz-1) for x in range(nx))
    for a,b,q,f in faces:out[a if q[f]>=0 else b]+=abs(q[f])
    factor=[min(1,h[i]*area/(dt*v)) if v else 1 for i,v in enumerate(out)]
    for a,b,q,f in faces:
        q[f]*=factor[a if q[f]>=0 else b];dh=q[f]*dt/area;h[a]-=dh;h[b]+=dh
    for i in range(len(h)):h[i]=max(0,h[i])

class Native:
    def __init__(self,path):
        self.dll=C.CDLL(str(path));self.step=self.dll.FluidStep
        self.step.argtypes=[C.c_int,C.c_int,*([C.c_void_p]*6),*([C.c_double]*4)];self.step.restype=C.c_int
    def __call__(self,state,dt):
        pointers=[C.c_void_p(a.buffer_info()[0]) for a in (state.h,state.bed,state.solid,state.qx,state.qz,state.factor)];c=state.config
        if not self.step(state.nx,state.nz,*pointers,c['cellSize'],dt,c['gravity'],c['damping']):raise RuntimeError('Native liquid step failed')

def native_backend():
    root=Path(__file__).resolve().parent
    path=Path(os.environ.get('MYENGINE_FLUID_LIBRARY',root/('FluidNative.dll' if sys.platform=='win32' else 'platforms/linux/libFluidNative.so')))
    return Native(path) if path.is_file() else None

def mesh_from_state(s):
    nx,nz=s.nx,s.nz;cell=s.config['cellSize'];rows=[]
    for z in range(nz+1):
        row=[]
        for x in range(nx+1):
            ids=[iz*nx+ix for iz in (z-1,z) for ix in (x-1,x) if 0<=ix<nx and 0<=iz<nz and not s.solid[iz*nx+ix]]
            row.append(sum(s.bed[i]+s.h[i] for i in ids)/len(ids) if ids else 0.)
        rows.append(row)
    points=[]
    for z in range(nz+1):
        for x in range(nx+1):
            left,right=max(0,x-1),min(nx,x+1);back,front=max(0,z-1),min(nz,z+1)
            dx=(rows[z][right]-rows[z][left])/((right-left)*cell);dz=(rows[front][x]-rows[back][x])/((front-back)*cell)
            length=math.sqrt(1+dx*dx+dz*dz)
            points.append(((x-nx*.5)*cell,rows[z][x],(z-nz*.5)*cell,-dx/length,1/length,-dz/length,x/nx,z/nz))
    output=array('f')
    for z in range(nz):
        for x in range(nx):
            i=z*nx+x
            if s.solid[i] or s.h[i]<1e-6:continue
            a=z*(nx+1)+x;b=a+1;d=a+nx+1;e=d+1
            for j in (a,d,b,b,d,e):output.extend(points[j])
    if not output:return None
    return MeshData(output,(-nx*cell*.5,min(output[1::8]),-nz*cell*.5),(nx*cell*.5,max(output[1::8]),nz*cell*.5))

def simulate(state,dt,commands,step):
    for command in commands:state.command(*command)
    # CFL bound for gravity waves; donor limiting also prevents negative depth.
    max_depth=max(state.h,default=0.);cell=state.config['cellSize'];g=state.config['gravity']
    limit=min(1/60,.2*cell/max(.01,math.sqrt(g*max_depth)))
    count=max(1,math.ceil(dt/limit))
    if count>4096:raise ValueError('Liquid step too large; reduce depth/impulse or increase cellSize')
    for _ in range(count):step(state,dt/count)
    return mesh_from_state(state),state.volume()

class Liquid:
    """Component API, called on the world owner thread. Positions are local X/Z."""
    def __init__(self,system,entity,config):
        self.system,self.entity=system,entity;self.config=settings(config);self.state=State(self.config)
        self.commands=[];self.future=None;self.elapsed=0.;self.volume=self.state.volume();self.layer=None;self.error='';self.closed=False
    def _queue(self,kind,x,z,amount,radius):
        self.entity._check()
        values=tuple(float(v) for v in (x,z,amount,radius))
        x,z,amount,radius=values
        if not all(math.isfinite(v) for v in values) or not 0<radius<=100 or abs(amount)>100:raise ValueError('Liquid command: finite numbers, radius 0..100 and amount -100..100')
        if kind=='water' and amount<0:raise ValueError('Added volume must be nonnegative')
        if self.closed:raise RuntimeError('Liquid component removed')
        if len(self.commands)>=256:raise RuntimeError('Liquid command queue full')
        self.commands.append((kind,*values))
    def add_water(self,x=0,z=0,volume=.1,radius=.6):self._queue('water',x,z,volume,radius)
    def splash(self,x=0,z=0,strength=2.,radius=1.):self._queue('splash',x,z,strength,radius)

class LiquidSystem:
    def __init__(self,world):
        self.world=world;self.components={};self.pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='liquid')
        self.native=native_backend();self.step=self.native or python_step
        if self.native is None:world.log('LIQUID: run build.cmd for FluidNative.dll. Using Python fallback.')
    def add(self,entity,config):
        if entity.is_4d or entity.voxels or entity.rigidbody or entity.collider:raise ValueError('Liquid requires its own entity without 4D model, voxels or rigidbody/collider')
        if entity.uid in self.components:self.remove(entity)
        if len(self.components)>=32:raise ValueError('Maximum 32 liquid pools per scene')
        c=Liquid(self,entity,config);self.components[entity.uid]=c;entity.liquid=c
        self.apply(c,mesh_from_state(c.state));return c
    def apply(self,c,mesh):
        from engine_runtime import Layer
        layer=Layer(self.world.core.create_mesh(mesh),mesh.minimum,mesh.maximum,mesh) if mesh is not None else None
        old=c.layer;c.layer=layer
        c.entity.layers=[layer] if layer else [];c.entity.source_layers=c.entity.layers
        if old:
            self.world.physics.geometry.pop(old.id,None);self.world.core.delete_mesh(old.id)
        c.entity.sync()
    def tick(self,dt):
        for c in tuple(self.components.values()):
            if c.closed or c.error or c.entity.destroyed:continue
            if c.future and c.future.done():
                try:
                    mesh,c.volume=c.future.result();self.apply(c,mesh)
                except Exception as ex:c.error=str(ex);self.world.log('LIQUID:',c.entity.name,c.error)
                c.future=None
            if not c.entity.active:continue
            c.elapsed=min(.1,c.elapsed+dt)
            if not c.error and c.future is None and c.elapsed>=1/c.config['updateHz']:
                commands,c.commands=c.commands,[];dt_job=min(.1,c.elapsed);c.elapsed-=dt_job
                c.future=self.pool.submit(simulate,c.state,dt_job,commands,self.step)
    def remove(self,entity):
        c=self.components.pop(entity.uid,None)
        if c is None:return
        c.closed=True
        if c.future:c.future.cancel()
        if c.layer:
            self.world.physics.geometry.pop(c.layer.id,None);self.world.core.delete_mesh(c.layer.id);c.layer=None
        entity.liquid=None;entity.layers=self.world.resources.model(entity.model);entity.source_layers=entity.layers
    def close(self):
        self.pool.shutdown(wait=True,cancel_futures=True)
        for c in list(self.components.values()):self.remove(c.entity)
