"""Amortized, double-buffered local cubemap of actual geometry and scene sky."""
import ctypes as C
import math
import time
from engine_gl import F,I,U,P,inverse
from engine_materials import world_bounds

FACES=(((1,0,0),(0,-1,0)),((-1,0,0),(0,-1,0)),
       ((0,1,0),(0,0,1)),((0,-1,0),(0,0,-1)),
       ((0,0,1),(0,-1,0)),((0,0,-1),(0,-1,0)))

def face_matrices(center,face,distance):
    from engine_four_d import cross,dot
    direction,up=FACES[face];right=cross(direction,up);up=cross(right,direction)
    view=[right[0],up[0],-direction[0],0,right[1],up[1],-direction[1],0,
          right[2],up[2],-direction[2],0,-dot(right,center),-dot(up,center),dot(direction,center),1]
    near=.03;far=distance
    return view,[1,0,0,0,0,1,0,0,0,0,(far+near)/(near-far),-1,0,0,2*far*near/(near-far),0]

def capture_selection(world,budget):
    """Bounds select/cull real draws; bounds are never rendered as objects."""
    camera=tuple(world.camera.position);metals=[];objects=[]
    for index,e in enumerate(world.entities):
        if e.destroyed or not e.active or not e.visible:continue
        if not e.voxels and (not e._native.visible or not e._native.mesh):continue
        bounds=world_bounds(e)
        if bounds is None:continue
        lo,hi=bounds;center=tuple((lo[k]+hi[k])*.5 for k in range(3))
        row=(sum((center[k]-camera[k])**2 for k in range(3)),index,e,center,lo,hi)
        objects.append(row)
        if not e.voxels and getattr(e,'material',{}).get('metallic',0)>0 and getattr(e,'material',{}).get('reflectionStrength',0)>0:metals.append(row)
    if not metals:return None
    anchor=min(metals,key=lambda row:row[:2]);center=anchor[3];draws=[]
    for _,index,e,_,lo,hi in objects:
        if e is anchor[2]:continue
        distance=sum(max(lo[k]-center[k],0,center[k]-hi[k])**2 for k in range(3))
        if distance<=budget['distance']**2:draws.append((distance,index,e))
    return anchor[2],center,[row[2] for row in sorted(draws,key=lambda row:row[:2])[:budget['maxDraws']]]

class ReflectionProbe:
    def __init__(self,renderer):
        self.renderer=renderer;self.gl=renderer.gl;self.fbo=0;self.depth=0;self.textures=[];self.size=0
        self.front=0;self.back=1;self.face=0;self.ready=False;self.failed=False;self.next_update=0
        self.center=(0,0,0);self.front_center=(0,0,0);self.front_distance=40.;self.anchor=None;self.sky=None
    @property
    def texture(self):return self.textures[self.front] if self.ready else 0
    def allocate(self,size):
        if size==self.size:return
        self.release_buffers();gl=self.gl
        value=U();gl.fn('glGenFramebuffersEXT',None,I,P)(1,C.byref(value));self.fbo=value.value
        gl.fn('glGenRenderbuffersEXT',None,I,P)(1,C.byref(value));self.depth=value.value
        gl.fn('glBindRenderbufferEXT',None,U,U)(0x8D41,self.depth)
        gl.fn('glRenderbufferStorageEXT',None,U,U,I,I)(0x8D41,0x81A6,size,size)
        for _ in range(2):
            gl.fn('glGenTextures',None,I,P)(1,C.byref(value));self.textures.append(value.value)
            gl.fn('glActiveTexture',None,U)(0x84C3);gl.fn('glBindTexture',None,U,U)(0x8513,value.value)
            for face in range(6):gl.fn('glTexImage2D',None,U,I,I,I,I,I,U,U,P)(0x8515+face,0,0x8058,size,size,0,0x1908,0x1401,None)
            for parameter,setting in ((0x2801,0x2703),(0x2800,0x2601),(0x2802,0x812F),(0x2803,0x812F),(0x8072,0x812F)):
                gl.fn('glTexParameteri',None,U,U,I)(0x8513,parameter,setting)
        self.size=size;self.ready=False;self.face=0;self.front=0;self.back=1
    def update(self,world,voxel_pass,budget):
        if self.failed or not budget['enabled']:return
        now=time.monotonic()
        if now<self.next_update:return
        selection=capture_selection(world,budget)
        if selection is None:self.ready=False;return
        anchor,center,draws=selection;gl=self.gl
        old_fbo=I();old_program=I();old_renderbuffer=I()
        gl.fn('glGetIntegerv',None,U,P)(0x8CA6,C.byref(old_fbo));gl.fn('glGetIntegerv',None,U,P)(0x8B8D,C.byref(old_program))
        gl.fn('glGetIntegerv',None,U,P)(0x8CA7,C.byref(old_renderbuffer))
        gl.fn('glPushAttrib',None,U)(0xfffff)
        gl.fn('glMatrixMode',None,U)(0x1701);gl.fn('glPushMatrix',None)()
        gl.fn('glMatrixMode',None,U)(0x1700);gl.fn('glPushMatrix',None)()
        try:
            self.allocate(budget['size'])
            if self.anchor is not anchor:
                self.anchor=anchor;self.face=0
            if self.face==0:self.center=center;self.capture_distance=budget['distance']
            for _ in range(budget['facesPerFrame']):
                view,projection=face_matrices(self.center,self.face,self.capture_distance)
                gl.fn('glBindFramebufferEXT',None,U,U)(0x8D40,self.fbo)
                gl.fn('glFramebufferTexture2DEXT',None,U,U,U,U,I)(0x8D40,0x8CE0,0x8515+self.face,self.textures[self.back],0)
                gl.fn('glFramebufferRenderbufferEXT',None,U,U,U,U)(0x8D40,0x8D00,0x8D41,self.depth)
                gl.fn('glDrawBuffer',None,U)(0x8CE0);gl.fn('glReadBuffer',None,U)(0x8CE0)
                if gl.fn('glCheckFramebufferStatusEXT',U,U)(0x8D40)!=0x8CD5:raise RuntimeError('Reflection framebuffer is unsupported')
                gl.fn('glViewport',None,I,I,I,I)(0,0,self.size,self.size)
                gl.fn('glMatrixMode',None,U)(0x1701);gl.fn('glLoadMatrixf',None,P)((F*16)(*projection))
                gl.fn('glMatrixMode',None,U)(0x1700);gl.fn('glLoadMatrixf',None,P)((F*16)(*view))
                for cap in (0x0C11,0x0B44,0x0BE2,0x0B50,0x0BC0):gl.fn('glDisable',None,U)(cap)
                gl.fn('glColorMask',None,C.c_ubyte,C.c_ubyte,C.c_ubyte,C.c_ubyte)(1,1,1,1)
                gl.fn('glEnable',None,U)(0x0B71);gl.fn('glDepthMask',None,C.c_ubyte)(1);gl.fn('glDepthFunc',None,U)(0x0203)
                gl.fn('glClearDepth',None,C.c_double)(1);gl.fn('glClear',None,U)(0x4000|0x0100)
                if world.skybox or getattr(world,'sun',None):
                    if self.sky is None:
                        from engine_skybox import SkyboxPass
                        self.sky=SkyboxPass(self.renderer.root,gl)
                    self.sky.draw(world)
                renderer=self.renderer;program=renderer.program
                gl.fn('glUseProgram',None,U)(program);renderer.mat(program,'inverseView',inverse(view))
                renderer.v(program,'cameraPosition',self.center)
                renderer.i(program,'reflectionReady',0);renderer.i(program,'environmentMap',3)
                # Capture actual textured display lists. Metals are diffuse in the
                # probe, providing one bounce without a recursive render.
                renderer.draw_entities(world,program,capture=True,entities=draws)
                if voxel_pass:voxel_pass.draw(world,entities_override=draws)
                renderer.draw_transparent(world,voxel_pass,entities=draws,camera=self.center,capture=True)
                self.face+=1
                if self.face==6:
                    gl.fn('glActiveTexture',None,U)(0x84C3);gl.fn('glBindTexture',None,U,U)(0x8513,self.textures[self.back])
                    gl.fn('glGenerateMipmapEXT',None,U)(0x8513)
                    self.front,self.back=self.back,self.front;self.front_center=self.center;self.front_distance=self.capture_distance
                    self.face=0;self.ready=True
                    break  # Never publish a partially updated cubemap.
            self.next_update=now+budget['updateInterval']
        finally:
            gl.fn('glBindFramebufferEXT',None,U,U)(0x8D40,old_fbo.value)
            gl.fn('glBindRenderbufferEXT',None,U,U)(0x8D41,old_renderbuffer.value)
            gl.fn('glMatrixMode',None,U)(0x1700);gl.fn('glPopMatrix',None)()
            gl.fn('glMatrixMode',None,U)(0x1701);gl.fn('glPopMatrix',None)();gl.fn('glMatrixMode',None,U)(0x1700)
            gl.fn('glUseProgram',None,U)(old_program.value);gl.fn('glPopAttrib',None)()
    def release_buffers(self):
        gl=self.gl
        for texture in self.textures:
            value=U(texture);gl.fn('glDeleteTextures',None,I,P)(1,C.byref(value))
        if self.depth:
            value=U(self.depth);gl.fn('glDeleteRenderbuffersEXT',None,I,P)(1,C.byref(value))
        if self.fbo:
            value=U(self.fbo);gl.fn('glDeleteFramebuffersEXT',None,I,P)(1,C.byref(value))
        self.textures=[];self.depth=self.fbo=self.size=0;self.ready=False
    def close(self):
        self.release_buffers()
        if self.sky:self.sky.close();self.sky=None
