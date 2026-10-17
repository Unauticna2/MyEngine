"""Directional shadow map shared by polygon display lists and voxel ray marching."""
from pathlib import Path
import ctypes as C,math
from engine_gl import GL,F,I,U,P,multiply,inverse,model_matrix
from engine_collision import rotation_axes
from engine_assets import finite
from engine_materials import material_settings,reflection_settings,transparent,transparent_order

def settings(value=None):
 d=dict(value or {});d['enabled']=bool(d.get('enabled',True));d['size']=int(d.get('size',1024));d['distance']=finite(d.get('distance',30));d['bias']=finite(d.get('bias',.0006))
 if d['size'] not in (512,1024,2048):raise ValueError('Shadow size: 512 / 1024 / 2048')
 if not 1<=d['distance']<=500 or not 0<=d['bias']<=.02:raise ValueError('Invalid shadow distance/bias')
 return d

def light_matrices(center,direction,radius,size):
 from engine_four_d import unit,cross,dot
 l=unit(direction);right=unit(cross(tuple(-v for v in l),(0,0,1) if abs(l[1])>.95 else (0,1,0)));up=cross(l,right)
 step=radius*2/size
 # Snap the light-space center to texels to avoid shimmer under camera motion.
 r=round(dot(center,right)/step)*step;u=round(dot(center,up)/step)*step;depth=dot(center,l)
 center=tuple(right[k]*r+up[k]*u+l[k]*depth for k in range(3));eye=tuple(center[k]+l[k]*2*radius for k in range(3))
 view=[right[0],up[0],l[0],0,right[1],up[1],l[1],0,right[2],up[2],l[2],0,-dot(right,eye),-dot(up,eye),-dot(l,eye),1]
 near=.01;far=4*radius
 proj=[1/radius,0,0,0,0,1/radius,0,0,0,0,-2/(far-near),0,0,0,-(far+near)/(far-near),1]
 return view,proj

class SceneRenderer:
 def __init__(self,root,gl=None):
  self.gl=gl or GL();self.root=Path(root);self.program=0;self.depth_program=0;self.fbo=0;self.texture=0;self.size=0;self.locations={};self.capturing=False;self.matrix=None;self.ready=False;self.probe=None
  try:
   shader=self.root/'shaders';self.program=self.gl.compile((shader/'surface.vert').read_text(),(shader/'surface.frag').read_text().replace('// SHADOW_HELPERS',(shader/'shadow_common.glsl').read_text()).replace('// LIGHT_HELPERS',(shader/'lighting_common.glsl').read_text()))
   self.depth_program=self.gl.compile((shader/'shadow.vert').read_text(),(shader/'shadow.frag').read_text())
  except Exception:self.close();raise
 def loc(self,program,name):
  key=(program,name)
  if key not in self.locations:self.locations[key]=self.gl.fn('glGetUniformLocation',I,U,C.c_char_p)(program,name.encode())
  return self.locations[key]
 def i(self,program,name,value):self.gl.fn('glUniform1i',None,I,I)(self.loc(program,name),value)
 def f(self,program,name,value):self.gl.fn('glUniform1f',None,I,F)(self.loc(program,name),value)
 def v(self,program,name,value):self.gl.fn('glUniform3f',None,I,F,F,F)(self.loc(program,name),*value)
 def mat(self,program,name,value):self.gl.fn('glUniformMatrix4fv',None,I,I,C.c_ubyte,P)(self.loc(program,name),1,0,(F*16)(*value))
 def allocate(self,size):
  if self.size==size:return
  gl=self.gl;old=I();gl.fn('glGetIntegerv',None,U,P)(0x8CA6,C.byref(old))
  if self.texture:v=U(self.texture);gl.fn('glDeleteTextures',None,I,P)(1,C.byref(v));self.texture=0
  if not self.fbo:
   v=U();gl.fn('glGenFramebuffersEXT',None,I,P)(1,C.byref(v));self.fbo=v.value
  v=U();gl.fn('glGenTextures',None,I,P)(1,C.byref(v));self.texture=v.value
  gl.fn('glActiveTexture',None,U)(0x84C2);gl.fn('glBindTexture',None,U,U)(0x0DE1,self.texture)
  for param,value in ((0x2801,0x2600),(0x2800,0x2600),(0x2802,0x812F),(0x2803,0x812F),(0x884C,0)):
   gl.fn('glTexParameteri',None,U,U,I)(0x0DE1,param,value)
  gl.fn('glTexImage2D',None,U,I,I,I,I,I,U,U,P)(0x0DE1,0,0x81A6,size,size,0,0x1902,0x1405,None)
  try:
   gl.fn('glBindFramebufferEXT',None,U,U)(0x8D40,self.fbo)
   gl.fn('glFramebufferTexture2DEXT',None,U,U,U,U,I)(0x8D40,0x8D00,0x0DE1,self.texture,0)
   gl.fn('glDrawBuffer',None,U)(0);gl.fn('glReadBuffer',None,U)(0)
   if gl.fn('glCheckFramebufferStatusEXT',U,U)(0x8D40)!=0x8CD5:raise RuntimeError('Shadow framebuffer is unsupported')
   self.size=size
  finally:gl.fn('glBindFramebufferEXT',None,U,U)(0x8D40,old.value);gl.fn('glActiveTexture',None,U)(0x84C0)
 def uniforms(self,program,world,receive=True):
  enabled=self.ready and not self.capturing and world.shadows['enabled'] and receive
  self.i(program,'shadowsEnabled',int(enabled))
  if not enabled:return
  gl=self.gl;gl.fn('glActiveTexture',None,U)(0x84C2);gl.fn('glBindTexture',None,U,U)(0x0DE1,self.texture);gl.fn('glActiveTexture',None,U)(0x84C0)
  self.i(program,'shadowTexture',2);self.f(program,'shadowTexel',1/self.size);self.f(program,'shadowBias',world.shadows['bias']);self.mat(program,'shadowMatrix',self.matrix)
 def draw_entities(self,world,program,depth=False,capture=False,entities=None,alpha_pass=False):
  gl=self.gl;self.i(program,'baseTexture',0)
  if not depth:
   from engine_lighting import upload
   upload(self,program,world)
  for e in (world.entities if entities is None else entities):
   if e.destroyed or not e.active or not e.visible or not e._native.visible or depth and not e.cast_shadows:continue
   if depth and transparent(e) or not depth and transparent(e)!=alpha_pass:continue
   material=getattr(e,'material',None) or material_settings()
   gl.fn('glPushMatrix',None)()
   try:
    gl.fn('glMultMatrixf',None,P)((F*16)(*model_matrix(tuple(e.position),tuple(e.rotation),tuple(e.scale))))
    gl.fn('glColor3f',None,F,F,F)(*tuple(e.color));gl.fn('glActiveTexture',None,U)(0x84C0)
    gl.fn('glBindTexture',None,U,U)(0x0DE1,e._native.texture);self.i(program,'hasTexture',int(bool(e._native.texture)))
    if not depth:
     self.uniforms(program,world,e.receive_shadows)
     self.f(program,'opacity',material.get('opacity',1));self.f(program,'alphaCutoff',material.get('alphaCutoff',.1))
     self.i(program,'alphaMode',{'opaque':0,'cutout':1,'transparent':2}[material.get('mode','opaque')])
     for key in ('metallic','roughness','reflectionStrength'):self.f(program,key,0. if capture and key=='metallic' else material[key])
    if depth:
     self.f(program,'opacity',material.get('opacity',1));self.f(program,'alphaCutoff',material.get('alphaCutoff',.1))
     self.i(program,'alphaMode',int(material.get('mode')=='cutout'))
    if alpha_pass and material.get('twoSided',True):
     gl.fn('glEnable',None,U)(0x0B44);gl.fn('glCullFace',None,U)(0x0404)
     gl.fn('glCallList',None,U)(e._native.mesh)
     gl.fn('glCullFace',None,U)(0x0405);gl.fn('glCallList',None,U)(e._native.mesh)
     gl.fn('glDisable',None,U)(0x0B44)
    else:
     if not material.get('twoSided',True):gl.fn('glEnable',None,U)(0x0B44);gl.fn('glCullFace',None,U)(0x0405)
     gl.fn('glCallList',None,U)(e._native.mesh)
     gl.fn('glDisable',None,U)(0x0B44)
   finally:gl.fn('glPopMatrix',None)()
 def shadow_map(self,world,voxel_pass):
  gl=self.gl;self.allocate(world.shadows['size']);view,proj=light_matrices(tuple(world.camera.position),world._light_frame['direction'],world.shadows['distance'],self.size);self.matrix=multiply(proj,view)
  old=I();gl.fn('glGetIntegerv',None,U,P)(0x8CA6,C.byref(old));self.capturing=True
  gl.fn('glMatrixMode',None,U)(0x1701);gl.fn('glPushMatrix',None)();gl.fn('glLoadMatrixf',None,P)((F*16)(*proj))
  gl.fn('glMatrixMode',None,U)(0x1700);gl.fn('glPushMatrix',None)();gl.fn('glLoadMatrixf',None,P)((F*16)(*view))
  gl.fn('glPushAttrib',None,U)(0xfffff)
  try:
   gl.fn('glBindFramebufferEXT',None,U,U)(0x8D40,self.fbo);gl.fn('glViewport',None,I,I,I,I)(0,0,self.size,self.size)
   gl.fn('glClearDepth',None,C.c_double)(1);gl.fn('glDepthMask',None,C.c_ubyte)(1);gl.fn('glEnable',None,U)(0x0B71);gl.fn('glDepthFunc',None,U)(0x0201);gl.fn('glClear',None,U)(0x0100)
   for cap in (0x0B44,0x0BE2,0x0B50,0x0BC0):gl.fn('glDisable',None,U)(cap)
   gl.fn('glEnable',None,U)(0x8037);gl.fn('glPolygonOffset',None,F,F)(2,4)
   gl.fn('glUseProgram',None,U)(self.depth_program);self.draw_entities(world,self.depth_program,True)
   gl.fn('glDisable',None,U)(0x8037)
   if voxel_pass:voxel_pass.draw(world,shadow=True)
   self.ready=True
  finally:
   self.capturing=False;gl.fn('glBindFramebufferEXT',None,U,U)(0x8D40,old.value);gl.fn('glPopAttrib',None)()
   gl.fn('glMatrixMode',None,U)(0x1700);gl.fn('glPopMatrix',None)();gl.fn('glMatrixMode',None,U)(0x1701);gl.fn('glPopMatrix',None)();gl.fn('glMatrixMode',None,U)(0x1700)
 def draw(self,world,voxel_pass=None):
  gl=self.gl;previous=I();gl.fn('glGetIntegerv',None,U,P)(0x8B8D,C.byref(previous));gl.fn('glPushAttrib',None,U)(0xfffff)
  try:
   if world.shadows['enabled'] and (world._light_frame['legacy'] or world._light_frame['shadow']>=0):self.shadow_map(world,voxel_pass)
   else:self.ready=False
   direction=world._light_frame['direction']
   gl.fn('glUseProgram',None,U)(self.program);self.v(self.program,'lightDirection',direction)
   # Reserve the sampler even before the first capture (GL forbids mixed
   # sampler types on one texture unit, including in disabled branches).
   self.i(self.program,'environmentMap',3)
   budget=getattr(world,'reflections',None) or reflection_settings()
   if self.probe is None:
    from engine_reflections import ReflectionProbe
    self.probe=ReflectionProbe(self)
   try:self.probe.update(world,voxel_pass,budget)
   except Exception as error:
    self.probe.failed=True;self.probe.ready=False;world.log('REFLECTION CAPTURE: '+str(error))
   view=(F*16)();gl.fn('glGetFloatv',None,U,P)(0x0BA6,view)
   gl.fn('glUseProgram',None,U)(self.program);self.mat(self.program,'inverseView',inverse(view))
   self.v(self.program,'lightDirection',direction)
   self.v(self.program,'cameraPosition',tuple(world.camera.position))
   available=budget['enabled'] and self.probe.ready and not self.probe.failed
   self.i(self.program,'reflectionReady',int(available));self.i(self.program,'environmentMap',3)
   if available:
    gl.fn('glActiveTexture',None,U)(0x84C3);gl.fn('glBindTexture',None,U,U)(0x8513,self.probe.texture);gl.fn('glActiveTexture',None,U)(0x84C0)
    self.v(self.program,'reflectionCenter',self.probe.front_center);self.f(self.program,'reflectionDistance',self.probe.front_distance)
    self.f(self.program,'reflectionMaxLod',math.log2(self.probe.size))
   gl.fn('glEnable',None,U)(0x0B71);gl.fn('glDepthMask',None,C.c_ubyte)(1);gl.fn('glDepthFunc',None,U)(0x0203)
   for cap in (0x0B44,0x0BE2,0x0B50,0x0BC0):gl.fn('glDisable',None,U)(cap)
   self.draw_entities(world,self.program)
  finally:gl.fn('glUseProgram',None,U)(previous.value);gl.fn('glPopAttrib',None)()
 def draw_transparent(self,world,voxel_pass=None,entities=None,camera=None,capture=False):
  gl=self.gl;draws=transparent_order(world.entities if entities is None else entities,camera or tuple(world.camera.position))
  if not draws:return
  previous=I();gl.fn('glGetIntegerv',None,U,P)(0x8B8D,C.byref(previous));gl.fn('glPushAttrib',None,U)(0xfffff)
  try:
   if voxel_pass and any(e.voxels for e in draws):voxel_pass.capture_depth()
   gl.fn('glEnable',None,U)(0x0B71);gl.fn('glDepthMask',None,C.c_ubyte)(0)
   gl.fn('glEnable',None,U)(0x0BE2);gl.fn('glBlendFunc',None,U,U)(0x0302,0x0303)
   gl.fn('glDepthFunc',None,U)(0x0203)
   view=(F*16)();gl.fn('glGetFloatv',None,U,P)(0x0BA6,view)
   for e in draws:
    if e.voxels:
     if voxel_pass:voxel_pass.draw(world,entities_override=[e],alpha_pass=True)
    else:
     gl.fn('glUseProgram',None,U)(self.program);self.mat(self.program,'inverseView',inverse(view))
     self.v(self.program,'cameraPosition',camera or tuple(world.camera.position))
     if capture:self.i(self.program,'reflectionReady',0)
     self.draw_entities(world,self.program,capture=capture,entities=[e],alpha_pass=True)
  finally:gl.fn('glUseProgram',None,U)(previous.value);gl.fn('glPopAttrib',None)()
 def close(self):
  gl=self.gl
  if self.probe:self.probe.close();self.probe=None
  for program in (self.program,self.depth_program):
   if program:gl.fn('glDeleteProgram',None,U)(program)
  if self.texture:v=U(self.texture);gl.fn('glDeleteTextures',None,I,P)(1,C.byref(v))
  if self.fbo:v=U(self.fbo);gl.fn('glDeleteFramebuffersEXT',None,I,P)(1,C.byref(v))
  self.program=self.depth_program=self.fbo=self.texture=0
