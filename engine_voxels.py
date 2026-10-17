"""Dense voxel chunks, GPU grid ray marching, polygon-compatible depth."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import ctypes as C
import json
import math
from collections import OrderedDict
from engine_gl import GL, P, I, U, F, multiply, inverse, model_matrix
from engine_assets import finite
from engine_collision import rotation_axes


class VoxelStorage:
    def __init__(self,pixels):self.pixels=pixels;self.shared=False;self.colliders={}

class VoxelGrid:
    MAX_SIZE=256
    def __init__(self, size=(32,32,32), cell_size=.1):
        if len(size)!=3 or any(int(x)!=x or not 1<=x<=self.MAX_SIZE for x in size):
            raise ValueError('Voxel dimensions must be integers in 1..256')
        self.size=tuple(int(x) for x in size); self.cell_size=finite(cell_size)
        if self.cell_size<=0:raise ValueError('cellSize must be positive')
        self._storage=VoxelStorage(bytearray(math.prod(self.size)*4));self.revision=0
    def clone(self):
        g=object.__new__(VoxelGrid);g.size=self.size;g.cell_size=self.cell_size;g.revision=self.revision
        self._storage.shared=True;g._storage=self._storage;return g
    @property
    def pixels(self):return memoryview(self._storage.pixels).toreadonly()
    def get(self,x,y,z):
        if any(int(v)!=v or not 0<=v<n for v,n in zip((x,y,z),self.size)):raise IndexError('Voxel outside chunk')
        x,y,z=map(int,(x,y,z));sx,sy,_=self.size;o=4*(x+sx*(y+sy*z));return tuple(self._storage.pixels[o:o+4])
    def set(self,x,y,z,rgba=(255,255,255,255)):
        coords=(x,y,z)
        if any(int(v)!=v or not 0<=v<n for v,n in zip(coords,self.size)):raise IndexError('Voxel outside chunk')
        if len(rgba)!=4 or any(int(v)!=v or not 0<=v<=255 for v in rgba):raise ValueError('RGBA requires four bytes')
        x,y,z=map(int,coords);sx,sy,sz=self.size
        o=4*(x+sx*(y+sy*z))
        if self._storage.pixels[o:o+4]==bytes(rgba):return
        if self._storage.shared:self._storage=VoxelStorage(bytearray(self._storage.pixels))
        self._storage.pixels[o:o+4]=bytes(rgba);self._storage.colliders.clear();self.revision+=1
    @classmethod
    def load(cls,path,cell_size=None,model_index=None):
        if Path(path).suffix.lower()=='.vox':
            from engine_magica import VoxFile
            return VoxFile(path).grid(.1 if cell_size is None else cell_size,model_index)
        d=json.loads(Path(path).read_text(encoding='utf-8-sig'))
        g=cls(d.get('size',(32,32,32)),d.get('cellSize',.1) if cell_size is None else cell_size)
        generator=d.get('generator')
        if generator not in (None,'sphere','terrain','solid'):raise ValueError('Unknown voxel generator')
        sx,sy,sz=g.size
        if generator:
            rgba=tuple(d.get('color',(70,170,230,255)))
            for z in range(sz):
                for y in range(sy):
                    for x in range(sx):
                        filled=(generator=='solid' or
                            generator=='sphere' and sum(((v+.5)/n*2-1)**2 for v,n in zip((x,y,z),g.size))<.85**2 or
                            generator=='terrain' and y<sy*(.3+.10*math.sin(x*.22)+.10*math.cos(z*.19)))
                        if filled:g.set(x,y,z,rgba)
        for cell in d.get('cells',[]):
            if len(cell)!=7:raise ValueError('cells entries must be [x,y,z,r,g,b,a]')
            g.set(*cell[:3],cell[3:])
        g.revision=0;return g


@dataclass
class VoxelRenderer:
    grid:VoxelGrid
    enabled:bool=True
    w_size:float|None=None


class VoxelPass:
    def __init__(self,root,gl=None):
        self.gl=gl or GL();self.root=Path(root);self.program=0;self.depth_texture=0;self.textures=OrderedDict();self.uniforms={};self.texture_budget=128*1024*1024;self.protected=set();self.upload_count=0
        shaders=self.root/'shaders'
        self.program=self.gl.compile((shaders/'voxel.vert').read_text(),(shaders/'voxel.frag').read_text().replace('// SHADOW_HELPERS',(shaders/'shadow_common.glsl').read_text()).replace('// LIGHT_HELPERS',(shaders/'lighting_common.glsl').read_text()))
        for name in ('volume','gridSize','cellSize','inverseViewProjection','viewProjection','inverseModel',
                     'normalMatrix','viewport','tint','lightDirection','cameraPosition','boundaryBias','orthographic','shadowsEnabled','shadowTexture','alphaPass','opacity','voxelDensity','opaqueDepth','hasOpaqueDepth','alphaCutoff'):
            self.uniforms[name]=self.gl.fn('glGetUniformLocation',I,U,C.c_char_p)(self.program,name.encode())

    def matrix(self,name,values,n=4):
        raw=(F*len(values))(*values)
        self.gl.fn(f'glUniformMatrix{n}fv',None,I,I,C.c_ubyte,P)(self.uniforms[name],1,0,raw)
    def v3(self,name,values):self.gl.fn('glUniform3f',None,I,F,F,F)(self.uniforms[name],*values)
    def delete(self,texture):
        value=U(texture);self.gl.fn('glDeleteTextures',None,I,P)(1,C.byref(value))
    def upload(self,key,grid):
        gl=self.gl;key=(id(grid._storage),grid.size,grid.cell_size);previous=self.textures.get(key)
        texture=previous[1] if previous else U()
        if not previous:gl.fn('glGenTextures',None,I,P)(1,C.byref(texture));texture=texture.value
        gl.fn('glBindTexture',None,U,U)(0x806F,texture)
        if not previous:
            for param,value in ((0x2801,0x2600),(0x2800,0x2600),(0x2802,0x812F),(0x2803,0x812F),(0x8072,0x812F)):
                gl.fn('glTexParameteri',None,U,U,I)(0x806F,param,value)
        if not previous or previous[2]!=grid.revision:
            self.upload_count+=1
            raw=(C.c_ubyte*len(grid.pixels)).from_buffer(grid._storage.pixels)
            gl.fn('glPixelStorei',None,U,I)(0x0CF5,1)
            gl.fn('glTexImage3D',None,U,I,I,I,I,I,I,U,U,P)(0x806F,0,0x8058,*grid.size,0,0x1908,0x1401,raw)
            error=gl.fn('glGetError',U)()
            if error:
                if not previous:self.delete(texture)
                raise RuntimeError(f'Voxel texture upload failed: GL {error:#x}')
        self.textures[key]=(grid._storage,texture,grid.revision);self.textures.move_to_end(key)
        size=sum(len(entry[0].pixels) for entry in self.textures.values())
        for old in tuple(self.textures):
            if size<=self.texture_budget:break
            if old not in self.protected:
                entry=self.textures.pop(old);size-=len(entry[0].pixels);self.delete(entry[1])
    def draw(self,world,shadow=False,entities_override=None,alpha_pass=False):
        gl=self.gl
        from engine_materials import transparent
        all_entities=[e for e in (world.entities if entities_override is None else entities_override) if not e.destroyed and getattr(e,'voxels',None)]
        self.protected={(id(e.voxels.grid._storage),e.voxels.grid.size,e.voxels.grid.cell_size) for e in all_entities}
        entities=[e for e in all_entities if e.active and e.visible and e.voxels.enabled and (not shadow or getattr(e,'cast_shadows',True)) and
                  (e.voxels.w_size is None or abs(world.camera.w-e.w)<=e.voxels.w_size*.5)]
        entities=[e for e in entities if transparent(e)==alpha_pass and (not shadow or not transparent(e))]
        if not entities:return
        if len(entities)>32:raise ValueError('At most 32 visible voxel chunks per scene in this version')
        view=(F*16)();proj=(F*16)();viewport=(I*4)();previous=I()
        gl.fn('glGetFloatv',None,U,P)(0x0BA6,view);gl.fn('glGetFloatv',None,U,P)(0x0BA7,proj)
        gl.fn('glGetIntegerv',None,U,P)(0x0BA2,viewport)
        gl.fn('glGetIntegerv',None,U,P)(0x8B8D,C.byref(previous))
        vp=multiply(proj,view)
        gl.fn('glPushAttrib',None,U)(0x000fffff)
        try:
            for cap in (0x0B50,0x0BE2,0x0BC0,0x0B44):gl.fn('glDisable',None,U)(cap)
            gl.fn('glEnable',None,U)(0x0B71);gl.fn('glDepthMask',None,C.c_ubyte)(int(not alpha_pass))
            if alpha_pass:
                gl.fn('glEnable',None,U)(0x0BE2);gl.fn('glBlendFunc',None,U,U)(0x0302,0x0303)
            gl.fn('glDepthFunc',None,U)(0x0203)
            gl.fn('glActiveTexture',None,U)(0x84C0)
            gl.fn('glUseProgram',None,U)(self.program)
            gl.fn('glUniform1i',None,I,I)(self.uniforms['volume'],0)
            # GLSL rejects different sampler types on one unit even when the branch
            # using one of them is disabled. Reserve unit 2 for the depth texture.
            gl.fn('glUniform1i',None,I,I)(self.uniforms['shadowTexture'],2)
            gl.fn('glUniform4f',None,I,F,F,F,F)(self.uniforms['viewport'],*viewport)
            self.matrix('viewProjection',vp);self.matrix('inverseViewProjection',inverse(vp))
            self.v3('cameraPosition',inverse(view)[12:15])
            gl.fn('glUniform1i',None,I,I)(self.uniforms['orthographic'],int(abs(proj[15]-1)<1e-6))
            gl.fn('glUniform1f',None,I,F)(self.uniforms['boundaryBias'],getattr(world,'voxel_boundary_bias',1e-5))
            renderer=getattr(world,'scene_renderer',None)
            if renderer:
                from engine_lighting import upload
                upload(renderer,self.program,world)
            self.v3('lightDirection',(getattr(world,'_light_frame',None) or {}).get('direction',rotation_axes(tuple(world.light_rotation))[1]))
            gl.fn('glUniform1i',None,I,I)(self.uniforms['alphaPass'],int(alpha_pass))
            gl.fn('glUniform1i',None,I,I)(self.uniforms['opaqueDepth'],1)
            gl.fn('glUniform1i',None,I,I)(self.uniforms['hasOpaqueDepth'],int(alpha_pass and bool(self.depth_texture)))
            if alpha_pass and self.depth_texture:
                gl.fn('glActiveTexture',None,U)(0x84C1);gl.fn('glBindTexture',None,U,U)(0x0DE1,self.depth_texture)
                gl.fn('glActiveTexture',None,U)(0x84C0)
            for e in entities:
                renderer=getattr(world,'scene_renderer',None)
                if renderer:renderer.uniforms(self.program,world,getattr(e,'receive_shadows',True) and not shadow)
                else:gl.fn('glUniform1i',None,I,I)(self.uniforms['shadowsEnabled'],0)
                material=getattr(e,'material',None) or {}
                gl.fn('glUniform1f',None,I,F)(self.uniforms['opacity'],material.get('opacity',1.))
                gl.fn('glUniform1f',None,I,F)(self.uniforms['voxelDensity'],material.get('voxelDensity',1.))
                gl.fn('glUniform1f',None,I,F)(self.uniforms['alphaCutoff'],material.get('alphaCutoff',.1) if material.get('mode')=='cutout' else .5)
                grid=e.voxels.grid;self.upload(e.uid,grid)
                m=model_matrix(tuple(e.position),tuple(e.rotation),tuple(e.scale));im=inverse(m)
                # Restrict ray marching to the projected chunk rectangle, especially
                # important for small chunks in the directional shadow map.
                clip=multiply(vp,m);half=[n*grid.cell_size*.5 for n in grid.size]
                corners=[]
                for ix in (-1,1):
                    for iy in (-1,1):
                        for iz in (-1,1):
                            q=(ix*half[0],iy*half[1],iz*half[2],1)
                            corners.append([sum(clip[k*4+r]*q[k] for k in range(4)) for r in range(4)])
                gl.fn('glEnable',None,U)(0x0C11)
                if all(q[3]>1e-6 for q in corners):
                    xs=[(q[0]/q[3]+1)*viewport[2]*.5+viewport[0] for q in corners];ys=[(q[1]/q[3]+1)*viewport[3]*.5+viewport[1] for q in corners]
                    x0=max(viewport[0],math.floor(min(xs))-2);x1=min(viewport[0]+viewport[2],math.ceil(max(xs))+2)
                    y0=max(viewport[1],math.floor(min(ys))-2);y1=min(viewport[1]+viewport[3],math.ceil(max(ys))+2)
                    if x1<=x0 or y1<=y0:continue
                    gl.fn('glScissor',None,I,I,I,I)(x0,y0,x1-x0,y1-y0)
                else:gl.fn('glScissor',None,I,I,I,I)(*viewport)
                self.matrix('inverseModel',im)
                # Transpose of inverse model's upper-left 3x3: nonuniform scale is supported.
                self.matrix('normalMatrix',[im[r*4+c] for c in range(3) for r in range(3)],3)
                self.v3('gridSize',grid.size);self.v3('tint',tuple(e.color))
                gl.fn('glUniform1f',None,I,F)(self.uniforms['cellSize'],grid.cell_size)
                gl.fn('glBegin',None,U)(0x0007)
                for x,y in ((-1,-1),(1,-1),(1,1),(-1,1)):gl.fn('glVertex2f',None,F,F)(x,y)
                gl.fn('glEnd',None)()
        finally:
            gl.fn('glUseProgram',None,U)(previous.value);gl.fn('glPopAttrib',None)()
    def capture_depth(self):
        gl=self.gl;viewport=(I*4)();gl.fn('glGetIntegerv',None,U,P)(0x0BA2,viewport)
        gl.fn('glPushAttrib',None,U)(0xfffff)
        try:
            if not self.depth_texture:
                texture=U();gl.fn('glGenTextures',None,I,P)(1,C.byref(texture));self.depth_texture=texture.value
            gl.fn('glActiveTexture',None,U)(0x84C1);gl.fn('glBindTexture',None,U,U)(0x0DE1,self.depth_texture)
            for key,value in ((0x2801,0x2600),(0x2800,0x2600),(0x2802,0x812F),(0x2803,0x812F),(0x884C,0)):
                gl.fn('glTexParameteri',None,U,U,I)(0x0DE1,key,value)
            gl.fn('glCopyTexImage2D',None,U,I,U,I,I,I,I,I)(0x0DE1,0,0x81A6,*viewport,0)
        finally:gl.fn('glPopAttrib',None)()
    def close(self):
        for _,texture,_ in self.textures.values():self.delete(texture)
        self.textures.clear()
        if self.depth_texture:self.delete(self.depth_texture);self.depth_texture=0
        if self.program:self.gl.fn('glDeleteProgram',None,U)(self.program);self.program=0
