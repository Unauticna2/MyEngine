"""Embedded Python runtime: ECS components, scripting, assets, 4D slices and triggers."""
from __future__ import annotations
import ctypes as C
from concurrent.futures import ThreadPoolExecutor
import os
from dataclasses import dataclass, field
import json
import heapq
import math
from pathlib import Path
import sys
import threading
import traceback
import types

from engine_assets import asset_path, finite, load_layers, load_texture, slice_index
from engine_physics import Collider as BoxCollider, Rigidbody, PhysicsWorld, xyz, positive


class Vec3(C.Structure):
    _fields_=[('x',C.c_float),('y',C.c_float),('z',C.c_float)]
    def __iter__(self):return iter((self.x,self.y,self.z))
    def __repr__(self):return f'Vec3({self.x:g}, {self.y:g}, {self.z:g})'
    def set(self,x,y,z):self.x,self.y,self.z=finite(x),finite(y),finite(z)


class NativeEntity(C.Structure):
    _fields_=[('position',Vec3),('rotation',Vec3),('scale',Vec3),('color',Vec3),
              ('mesh',C.c_uint32),('texture',C.c_uint32),('visible',C.c_uint32),('w',C.c_float)]
assert C.sizeof(NativeEntity)==64 and NativeEntity.mesh.offset==48


def vec(value,default=(0,0,0),keys=('x','y','z')):
    if value is None:return tuple(default)
    if isinstance(value,dict):return tuple(finite(value.get(k,default[i])) for i,k in enumerate(keys))
    values=tuple(value)
    if len(values)!=3:raise ValueError('Vector requires exactly three values')
    return tuple(finite(v) for v in values)


class NativeCore:
    def __init__(self):
        if sys.platform!='win32':raise RuntimeError('The native engine runs on Windows x64')
        kernel=C.WinDLL('kernel32',use_last_error=True)
        kernel.GetModuleHandleW.argtypes=[C.c_wchar_p]
        kernel.GetModuleHandleW.restype=C.c_void_p
        self.dll=C.CDLL(None,handle=kernel.GetModuleHandleW(None))
        for name in ('EngineGetCamera','EngineGetKeys','EngineGetLight','EngineGetDelta','EngineGetWindow'):
            f=getattr(self.dll,name);f.argtypes=[];f.restype=C.c_void_p
        signatures={
            'EngineSubmitScene':([C.c_void_p,C.c_uint32],C.c_int),
            'EngineCreateMesh':([C.c_void_p,C.c_uint32],C.c_uint32),
            'EngineDeleteMesh':([C.c_uint32],None),
            'EngineCreateTexture':([C.c_void_p,C.c_uint32,C.c_uint32],C.c_uint32),
            'EngineDeleteTexture':([C.c_uint32],None)}
        for name,(args,result) in signatures.items():
            f=getattr(self.dll,name);f.argtypes=args;f.restype=result
        self.camera=(C.c_float*6).from_address(self.dll.EngineGetCamera())
        self.light=Vec3.from_address(self.dll.EngineGetLight())
        self.keys=(C.c_ubyte*256).from_address(self.dll.EngineGetKeys())
        self.delta=C.c_float.from_address(self.dll.EngineGetDelta())
        self.hwnd=self.dll.EngineGetWindow()
        self.user=C.WinDLL('user32',use_last_error=True)
        self.user.SetWindowTextW.argtypes=[C.c_void_p,C.c_wchar_p]
        self.user.SetWindowTextW.restype=C.c_int
        try:f=self.dll.EngineGetCameraControl
        except AttributeError:raise RuntimeError('Old EXE: run build.cmd to rebuild with Physics.asm and new exports') from None
        f.argtypes=[];f.restype=C.c_void_p
        self.camera_control=C.c_uint32.from_address(f())
        try:f=self.dll.EngineGetRenderFlags
        except AttributeError:raise RuntimeError('Rebuild MyEngine2.exe with the 2.5 build.cmd') from None
        f.argtypes=[];f.restype=C.c_void_p;self.render_flags=C.c_uint32.from_address(f())
        try:f=self.dll.EngineGetRuntimeFlags
        except AttributeError:raise RuntimeError('Rebuild MyEngine2.exe with the 2.5 build.cmd') from None
        f.argtypes=[];f.restype=C.c_void_p;self.runtime_flags=C.c_uint32.from_address(f())
        self.owner_thread=threading.get_ident()

    def arguments(self):
        kernel=C.WinDLL('kernel32')
        shell=C.WinDLL('shell32')
        kernel.GetCommandLineW.argtypes=[];kernel.GetCommandLineW.restype=C.c_wchar_p
        shell.CommandLineToArgvW.argtypes=[C.c_wchar_p,C.POINTER(C.c_int)]
        shell.CommandLineToArgvW.restype=C.POINTER(C.c_wchar_p)
        kernel.LocalFree.argtypes=[C.c_void_p];kernel.LocalFree.restype=C.c_void_p
        count=C.c_int();argv=shell.CommandLineToArgvW(kernel.GetCommandLineW(),C.byref(count))
        if not argv:return []
        try:return [argv[i] for i in range(1,count.value)]
        finally:kernel.LocalFree(C.cast(argv,C.c_void_p))

    def assert_thread(self):
        if threading.get_ident()!=self.owner_thread:
            raise RuntimeError('Change engine resources on the update thread, not a background thread')

    def create_mesh(self,mesh):
        self.assert_thread()
        raw=(C.c_float*len(mesh.vertices)).from_buffer(mesh.vertices)
        result=self.dll.EngineCreateMesh(raw,len(mesh.vertices)//8)
        if not result:raise RuntimeError('OpenGL mesh creation failed')
        return result

    def create_texture(self,image):
        self.assert_thread()
        w,h,pixels=image
        raw=C.create_string_buffer(pixels)
        result=self.dll.EngineCreateTexture(raw,w,h)
        if not result:raise RuntimeError(f'OpenGL texture creation failed ({w}x{h})')
        return result

    def submit(self,entities):
        self.assert_thread()
        if not self.dll.EngineSubmitScene(C.addressof(entities),len(entities)):
            raise RuntimeError('Native scene capacity exceeded')
    def clear(self):self.dll.EngineSubmitScene(None,0)
    def delete_mesh(self,id):self.dll.EngineDeleteMesh(id)
    def delete_texture(self,id):self.dll.EngineDeleteTexture(id)
    def set_title(self,text):self.user.SetWindowTextW(self.hwnd,text)
    def pointer(self):
        class Point(C.Structure):_fields_=[('x',C.c_long),('y',C.c_long)]
        class Rect(C.Structure):_fields_=[('left',C.c_long),('top',C.c_long),('right',C.c_long),('bottom',C.c_long)]
        self.user.GetCursorPos.argtypes=[C.POINTER(Point)];self.user.ScreenToClient.argtypes=[C.c_void_p,C.POINTER(Point)]
        self.user.GetClientRect.argtypes=[C.c_void_p,C.POINTER(Rect)];self.user.GetAsyncKeyState.argtypes=[C.c_int];self.user.GetAsyncKeyState.restype=C.c_short
        p=Point();r=Rect();self.user.GetCursorPos(C.byref(p));self.user.ScreenToClient(self.hwnd,C.byref(p));self.user.GetClientRect(self.hwnd,C.byref(r))
        self.user.GetForegroundWindow.restype=C.c_void_p
        focused=self.user.GetForegroundWindow()==self.hwnd
        return p.x if focused else -1,p.y if focused else -1,focused and bool(self.user.GetAsyncKeyState(1)&0x8000),r.right,r.bottom


@dataclass
class Layer:
    id:int
    minimum:tuple
    maximum:tuple
    geometry:object


class Resources:
    def __init__(self,core,root):
        from engine_resource_cache import shared
        self.core,self.root=core,root;self.cache=shared(core);self.leases={};self.paths={}
        self.meshes={};self.textures={};self.voxel_grids={};self.data_assets={}
    def path(self,name):
        if name not in self.paths:self.paths[name]=asset_path(self.root,name)
        return self.paths[name]
    def acquire(self,kind,path,loader,size=lambda v:0,dispose=lambda v:None,extra=()):
        key=self.cache.key(kind,path,extra)
        if key not in self.leases:self.leases[key]=self.cache.get(key,loader,size,dispose)
        return self.leases[key]
    def _compile(self,meshes):
        result=[]
        try:
            for mesh in meshes:result.append(Layer(self.core.create_mesh(mesh),mesh.minimum,mesh.maximum,mesh))
        except Exception:
            for layer in result:self.core.delete_mesh(layer.id)
            raise
        return result
    def preload(self,model_names,texture_names,voxel_names=()):
        # Reused assets never enter the decoder or allocate new GL resources.
        models=list(dict.fromkeys(p for p in model_names if p and Path(p).suffix.lower()!='.vox'));textures=list(dict.fromkeys(p for p in texture_names if p));jobs={}
        for kind,names,decode in [('mesh',models,load_layers),('texture',textures,load_texture)]:
            for name in names:
                path=self.path(name)
                if self.cache.key(kind,path) not in self.cache.entries:jobs[kind,name]=self.cache.pool.submit(decode,path)
        from engine_voxels import VoxelGrid
        voxel_jobs={}
        for value in [p for p in model_names if p and Path(p).suffix.lower()=='.vox']+list(voxel_names):
            if not value:continue
            settings={'path':value} if isinstance(value,str) else value
            path=self.path(settings['path']);extra=(settings.get('cellSize'),settings.get('modelIndex'));key=(path,*extra)
            if key in voxel_jobs:continue
            future=None
            if self.cache.key('voxel',path,extra) not in self.cache.entries:future=self.cache.pool.submit(VoxelGrid.load,path,*extra)
            voxel_jobs[key]=(settings,future)
        for name in models:self.model(name,jobs.get(('mesh',name)))
        for name in textures:self.texture(name,jobs.get(('texture',name)))
        for settings,future in voxel_jobs.values():self.voxel(settings,future)
    def model(self,name,decoded=None):
        if not name:return []
        path=self.path(name)
        if path not in self.meshes:
            self.meshes[path]=self.acquire('mesh',path,lambda:self._compile(decoded.result() if decoded else load_layers(path)),
                lambda ls:sum(len(l.geometry.vertices)*8 for l in ls),
                lambda ls:[self.core.delete_mesh(l.id) for l in ls])
        return self.meshes[path]
    def texture(self,name,decoded=None):
        if not name:return 0
        path=self.path(name)
        if path not in self.textures:
            def load():
                image=decoded.result() if decoded else load_texture(path);return self.core.create_texture(image),image[0]*image[1]*4
            self.textures[path]=self.acquire('texture',path,load,lambda x:x[1],lambda x:self.core.delete_texture(x[0]))[0]
        return self.textures[path]
    def scriptable(self,name,clone=False):
        from engine_scriptable import ScriptableObject
        path=self.path(name)
        if path not in self.data_assets:self.data_assets[path]=ScriptableObject.load(path)
        value=self.data_assets[path];return value.clone() if clone else value
    def voxel(self,name,decoded=None):
        from engine_voxels import VoxelGrid,VoxelRenderer
        if name is None:return None
        settings={'path':name} if isinstance(name,str) else dict(name)
        path=self.path(settings['path']);extra=(settings.get('cellSize'),settings.get('modelIndex'));key=(path,*extra)
        if key not in self.voxel_grids:
            self.voxel_grids[key]=self.acquire('voxel',path,lambda:decoded.result() if decoded else VoxelGrid.load(path,*extra),lambda g:len(g.pixels),extra=extra)
        width=settings.get('wSize')
        if width is not None:width=positive(width,'wSize')
        return VoxelRenderer(self.voxel_grids[key].clone(),bool(settings.get('enabled',True)),width)
    def close(self):
        for key in self.leases:self.cache.release(key)
        self.leases.clear();self.data_assets.clear();self.voxel_grids.clear();self.meshes.clear();self.textures.clear();self.paths.clear()


_KEYS={'SPACE':32,'CTRL':17,'SHIFT':16,'ALT':18,'ESC':27,'ENTER':13,
       'LEFT':37,'UP':38,'RIGHT':39,'DOWN':40,'TAB':9}
_KEYS.update({f'F{i}':111+i for i in range(1,13)})
_KEYS.update({f'NUM{i}':96+i for i in range(10)})


class Input:
    def __init__(self):self.current=bytes(256);self.previous=bytes(256)
    def update(self,keys):self.previous,self.current=self.current,bytes(keys)
    @staticmethod
    def code(key):
        if isinstance(key,int):code=key
        else:
            key=str(key).upper()
            code=ord(key) if len(key)==1 else _KEYS[key]
        if not 0<=code<256:raise ValueError('Virtual key must be 0..255')
        return code
    def down(self,key):return bool(self.current[self.code(key)])
    def pressed(self,key):
        k=self.code(key);return bool(self.current[k] and not self.previous[k])
    def released(self,key):
        k=self.code(key);return bool(self.previous[k] and not self.current[k])
    def axis(self,negative,positive):return int(self.down(positive))-int(self.down(negative))


class Behaviour:
    """Subclass as Script. entity/world are assigned before start()."""
    entity:Entity
    world:World
    def start(self):pass
    enabled=True
    def update(self,dt):pass
    def fixed_update(self,dt):pass
    def on_collision_enter(self,collision):pass
    def on_collision_stay(self,collision):pass
    def on_collision_exit(self,collision):pass
    def on_trigger_enter(self,other):pass
    def on_trigger_stay(self,other):pass
    def on_trigger_exit(self,other):pass
    def on_destroy(self):pass


class ScriptBinding:
    def __init__(self,entity,path):
        self.entity,self.path=entity,path
        self.instance=None;self.enabled=True;self.started=False;self.module_name=f'_object_script_{entity.id}_{id(self)}'
    def reload(self,defer_start=False):
        if not self.entity.world.scripts_allowed or not getattr(self.entity,'script_trusted',True):
            self.enabled=False;return True
        try:
            module=types.ModuleType(self.module_name)
            module.__file__=str(self.path)
            old_module=sys.modules.get(self.module_name)
            sys.modules[self.module_name]=module
            try:
                exec(compile(self.path.read_text(encoding='utf-8-sig'),str(self.path),'exec'),module.__dict__)
                instance=module.Script()
                instance.entity=self.entity;instance.world=self.entity.world
            except Exception:
                if old_module is None:sys.modules.pop(self.module_name,None)
                else:sys.modules[self.module_name]=old_module
                raise
        except Exception:
            print(f'SCRIPT LOAD ERROR: {self.path}');traceback.print_exc()
            return False             # Keep a previous working instance on syntax errors.
        if self.instance is not None:self.call('on_destroy',force=True)
        self.instance=instance;self.enabled=True;self.started=False
        if not defer_start:self.call('start')
        return self.enabled
    def call(self,name,*args,force=False):
        if self.instance is None:return
        if name!='on_destroy' and (not self.entity.world.scripts_allowed or not getattr(self.entity,'script_trusted',True)):return
        if name=='on_destroy' and not self.started:return
        if not force and (not self.enabled or not getattr(self.instance,'enabled',True)):return
        if name=='start':
            if self.started:return
            self.started=True
        elif name!='on_destroy' and not self.started:return
        method=getattr(self.instance,name,None)
        if method is None:return
        try:method(*args)
        except Exception:
            self.enabled=False
            print(f'SCRIPT DISABLED: {self.entity.name}: {self.path}: {name}')
            traceback.print_exc()


class Entity:
    def __init__(self,world,id,native,name,model,spacing,uid):
        self.world,self.id,self._native,self.name,self.uid=world,id,native,name,uid
        self.script_trusted=True;self.cast_shadows=True;self.receive_shadows=True
        self.model=model;self.layers=world.resources.model(model);self.source_layers=self.layers
        self._slice_key=None;self._slice_layer=None;self.scale_w=1.;self.rotation4=Vec3()
        self.is_4d=bool(model and Path(model).suffix.lower()=='.4d')
        self.layer_spacing=spacing;self.layer=0
        self.active=True;self.visible=True;self.is_player=False;self.destroyed=False
        self.collider=None;self.rigidbody=None;self.scripts=[];self._texture=None;self.voxels=None
    def _check(self):
        self.world.assert_thread()
        if self.destroyed and not getattr(self,'_in_destroy',False):raise ReferenceError(f'{self.name} has been destroyed')
    @property
    def native(self):self._check();return self._native
    @property
    def position(self):return self.native.position
    @position.setter
    def position(self,v):self.native.position=Vec3(*vec(v))
    @property
    def rotation(self):return self.native.rotation
    @rotation.setter
    def rotation(self,v):self.native.rotation=Vec3(*vec(v))
    @property
    def scale(self):return self.native.scale
    @scale.setter
    def scale(self,v):
        v=vec(v)
        if min(abs(x) for x in v)<1e-5:raise ValueError('Scale must not contain zero')
        self.native.scale=Vec3(*v)
    @property
    def color(self):return self.native.color
    @color.setter
    def color(self,v):self.native.color=Vec3(*vec(v,keys=('r','g','b')))
    @property
    def w(self):return self.native.w
    @w.setter
    def w(self,v):self.native.w=finite(v)
    @property
    def texture(self):return self._texture
    @texture.setter
    def texture(self,name,decoded=None):
        self._check();self._native.texture=self.world.resources.texture(name);self._texture=name
    def move(self,x=0,y=0,z=0,w=0):
        self.position=tuple(a+b for a,b in zip(self.position,xyz((x,y,z))));self.w+=w
    def rotate(self,x=0,y=0,z=0):self.rotation=tuple(a+b for a,b in zip(self.rotation,xyz((x,y,z))))
    def add_voxels(self,path):
        self._check();self.voxels=self.world.resources.voxel(path);return self.voxels
    def set_voxel(self,x,y,z,rgba=(255,255,255,255)):
        self._check()
        if not self.voxels:raise ValueError('Object has no VoxelRenderer')
        self.voxels.grid.set(x,y,z,rgba)
    def add_box_collider(self,size=None,center=None,is_trigger=False,**settings):
        self._check()
        settings.update(type='box',size=size,center=center,isTrigger=is_trigger)
        self.collider=BoxCollider.from_json(settings);return self.collider
    def add_box_trigger(self,size=(1,1,1),center=(0,0,0),w_size=None):
        return self.add_box_collider(size,center,True,wSize=w_size)
    def add_mesh_collider(self,is_trigger=False,**settings):
        self._check()
        if not self.layers:raise ValueError('Mesh collider requires a model')
        if self.rigidbody and not self.rigidbody.is_kinematic:raise ValueError('Dynamic bodies require a box collider')
        settings.update(type='mesh',isTrigger=is_trigger)
        self.collider=BoxCollider.from_json(settings)
        return self.collider
    def add_rigidbody(self,**settings):
        self._check()
        if self.rigidbody is not None:raise ValueError('Object already has a Rigidbody')
        self.rigidbody=Rigidbody(self,**settings);return self.rigidbody
    def add_voxel_collider(self,is_trigger=False,**settings):
        self._check()
        if not self.voxels:raise ValueError('Voxel collider requires a voxel model')
        if self.rigidbody and not self.rigidbody.is_kinematic:raise ValueError('For a falling voxel object use Box Collider + Rigidbody')
        settings.update(type='voxel',isTrigger=is_trigger)
        self.collider=BoxCollider.from_json(settings);return self.collider
    def remove_rigidbody(self):
        self._check();self.rigidbody=None;self.world.physics.forget(self)
    def add_script(self,path):
        self._check();b=ScriptBinding(self,asset_path(self.world.root,path))
        if not b.reload(defer_start=True):raise ValueError(f'Cannot load script {path}; see engine.log')
        self.scripts.append(b);self.world._starts.append(b);return b.instance
    def get_script(self,path=None):
        self._check()
        for b in self.scripts:
            if path is None or b.path.name==Path(path).name:return b.instance
        return None
    def destroy(self):self.world.destroy(self)
    def release_slice(self):
        if self._slice_layer is not None:
            self.world.physics.geometry.pop(self._slice_layer.id,None)
            self.world.core.delete_mesh(self._slice_layer.id);self._slice_layer=None
        self._slice_key=None
    def sync(self):
        if self.destroyed:self._native.visible=0;return
        if self.is_4d:
            sw=finite(self.scale_w)
            if abs(sw)<1e-5:raise ValueError('W scale must not be zero')
            angles=tuple(finite(v) for v in self.rotation4)
            if any(abs(v%360)>1e-7 for v in angles):
                key=(self.world.camera.w-self.w,self.layer_spacing,sw,angles,tuple(self.scale))
                result=None
                if self.world._loading:
                    if key!=self._slice_key:
                        from engine_native4d import slice_layers
                        result=(key,slice_layers(self.source_layers,self.layer_spacing,sw,angles,tuple(self.scale),key[0]))
                else:
                    result=self.world.slice_jobs.get(self.uid,self.source_layers,key,self._slice_key)
                if result is not None and result[0]!=self._slice_key:
                    completed,geometry=result
                    layer=Layer(self.world.core.create_mesh(geometry),geometry.minimum,geometry.maximum,geometry) if geometry else None
                    self.release_slice();self._slice_layer=layer;self._slice_key=completed
                self.layers=[self._slice_layer] if self._slice_layer else []
                self.layer=0 if self.layers else None
            else:
                self.world.slice_jobs.cancel(self.uid)
                if self._slice_layer:self.release_slice()
                self.layers=self.source_layers
                self.layer=slice_index((self.world.camera.w-self.w)/sw,0,self.layer_spacing,len(self.layers))
        else:self.layer=0
        mesh=self.layers[self.layer].id if self.layers and self.layer is not None else 0
        self._native.mesh=mesh;self._native.visible=int(self.active and self.visible and bool(mesh))


class Camera:
    id=-1;uid=-1;name='player';is_player=True;active=True;destroyed=False
    def __init__(self,world):
        self.world=world;self.data=world.core.camera
        self._position=Vec3.from_buffer(self.data)
        self.collider=BoxCollider((.5,1.6,.5),(0,0,0),False)
        self.rigidbody=None;self.scripts=[];self.controller=None
    add_script=Entity.add_script
    get_script=Entity.get_script
    def configure_physics(self,mode="walk",**settings):
        self._check()
        from engine_character import CharacterController
        self.controller=CharacterController(self,mode,**settings)
        return self.controller
    def _check(self):
        self.world.assert_thread()
        if self.destroyed:raise ReferenceError('Camera belongs to a closed scene')
    @property
    def position(self):self._check();return self._position
    @position.setter
    def position(self,v):self._check();self._position.set(*xyz(v))
    @property
    def pitch(self):self._check();return self.data[3]
    @pitch.setter
    def pitch(self,v):self._check();self.data[3]=max(-89,min(89,finite(v)))
    @property
    def yaw(self):self._check();return self.data[4]
    @yaw.setter
    def yaw(self,v):self._check();self.data[4]=finite(v)%360
    @property
    def w(self):self._check();return self.data[5]
    @w.setter
    def w(self,v):self._check();self.data[5]=finite(v)
    @property
    def control_enabled(self):self._check();return bool(self.world.core.camera_control.value)
    @control_enabled.setter
    def control_enabled(self,v):self._check();self.world.core.camera_control.value=int(bool(v))
    def add_rigidbody(self,**settings):
        if self.rigidbody:raise ValueError('Camera already has a Rigidbody')
        settings['freeze_rotation']=True
        self.rigidbody=Rigidbody(self,**settings)
        self.control_enabled=False
        return self.rigidbody


class World:
    MAX_ENTITIES=4096
    def __init__(self,core,root):
        self.core,self.root=core,Path(root).resolve()
        self.owner_thread=threading.get_ident()
        from engine_trust import allowed
        self.scripts_allowed=allowed(self.root)
        self.resources=Resources(core,self.root)
        from engine_slice_jobs import SliceJobs
        self.slice_jobs=SliceJobs()
        self.entities=[];self.by_name={};self.native=(NativeEntity*self.MAX_ENTITIES)()
        self._native_count=0;self._free=[];self._next_uid=0;self._starts=[];self._destroy=[]
        self.camera=Camera(self);self.light_rotation=core.light
        self.input=Input();self.physics=PhysicsWorld(self)
        from engine_runtime_options import normalized
        self.runtime=normalized()
        self.time=0.;self.delta_time=0.;self.w_step=.1;self.title='MyEngine 2'
        self.editor_mode=bool(getattr(core,'editor_mode',False));self.voxel_pass=getattr(core,'voxel_pass',None);self.voxel_failed=False
        from engine_render import settings as shadow_settings
        self.shadows=shadow_settings();self.scene_renderer=None;self.render_failed=False;self.editor_outlines=False;self.sun=None
        self.skybox=None;self.skybox_pass=None;self.skybox_failed=False;self.voxel_boundary_bias=1e-5
        self.ui=None;self._screenshots=[];self._save_jobs=[]
        self._next_title=0.;self.closed=False;self.scene_path=None;self.pending_scene=None;self._loading=False
    def assert_thread(self):
        if threading.get_ident()!=self.owner_thread:raise RuntimeError('Use the engine API from update/callbacks')
    def find(self,name):return self.camera if name=='player' else self.by_name.get(name)
    def log(self,*args):print(*args,flush=True)
    @property
    def fixed_time(self):return self.physics.fixed_time
    def _submit(self):
        # NativeCore.submit accepts ctypes arrays; a view keeps the stable pool in place.
        self.core.submit((NativeEntity*self._native_count).from_buffer(self.native))
    def instantiate_prefab(self,path,position=(0,0,0),**settings):
        self.assert_thread()
        from engine_prefabs import instantiate_prefab
        return instantiate_prefab(self,path,position,**settings)
    def instantiate(self,model=None,*,name=None,position=(0,0,0),rotation=(0,0,0),scale=(1,1,1),
                    color=(1,1,1),texture=None,scripts=None,collider=None,rigidbody=None,w=0,layer_spacing=None,voxels=None,scale_w=1,rotation4=(0,0,0),trusted=True):
        self.assert_thread()
        if self.closed:raise RuntimeError('World is closed')
        if model is not None and not isinstance(model,str):raise ValueError('model must be a path or None')
        if model and Path(model).suffix.lower()=='.vox':
            if voxels is None:voxels=model
            model=None
        self._next_uid+=1;uid=self._next_uid
        name=str(name or f'entity_{uid}')
        if name=='player' or name in self.by_name:raise ValueError(f'Duplicate/reserved object name: {name}')
        if self._free:i=heapq.heappop(self._free)
        elif self._native_count<self.MAX_ENTITIES:i=self._native_count;self._native_count+=1
        else:raise RuntimeError('Scene capacity: 4096 objects')
        e=None
        try:
            C.memset(C.addressof(self.native[i]),0,C.sizeof(NativeEntity))
            e=Entity(self,i,self.native[i],name,model,positive(self.w_step if layer_spacing is None else layer_spacing,'layer_spacing'),uid)
            e.script_trusted=bool(trusted)
            e.position=position;e.rotation=rotation;e.scale=scale;e.color=color;e.w=w;e.texture=texture
            e.scale_w=finite(scale_w);e.rotation4.set(*vec(rotation4))
            if abs(e.scale_w)<1e-5:raise ValueError('W scale must not be zero')
            if voxels is not None:e.add_voxels(voxels)
            e.collider=collider if isinstance(collider,BoxCollider) else BoxCollider.from_json(collider)
            if e.collider and e.collider.kind=='voxel' and not e.voxels:raise ValueError('Voxel collider requires a voxel model')
            self.entities.append(e);self.by_name[name]=e
            if rigidbody is not None and rigidbody is not False:
                if e.collider is None:e.add_box_collider()
                e.add_rigidbody(**({} if rigidbody is True else rigidbody))
            if isinstance(scripts,str):scripts=[scripts]
            for path in scripts or []:e.add_script(path)
            e.sync()
            if not self._loading:self._submit()
            return e
        except Exception:
            if e is not None:
                for b in e.scripts:sys.modules.pop(b.module_name,None)
                self._starts=[b for b in self._starts if b.entity is not e]
                if e in self.entities:self.entities.remove(e)
                self.by_name.pop(name,None);e.destroyed=True;e._native.visible=0
                e.release_slice();self.physics.forget(e)
            heapq.heappush(self._free,i)
            raise
    def destroy(self,entity):
        self.assert_thread()
        if isinstance(entity,str):entity=self.find(entity)
        if entity is None:return
        if entity.is_player:raise ValueError('Cannot destroy the scene camera')
        if entity.world is not self:raise ValueError('Object belongs to another scene')
        if entity.destroyed:return
        entity.destroyed=True;entity.active=False;entity._native.visible=0
        self.by_name.pop(entity.name,None);self._destroy.append(entity)
    def _flush_destroy(self):
        pending,self._destroy=self._destroy,[]
        for e in pending:
            e._in_destroy=True
            for b in e.scripts:b.call('on_destroy',force=True);sys.modules.pop(b.module_name,None)
            e._in_destroy=False
            self._starts=[b for b in self._starts if b.entity is not e]
            if e in self.entities:self.entities.remove(e)
            self.slice_jobs.cancel(e.uid);e.release_slice();self.physics.forget(e);heapq.heappush(self._free,e.id)
    def _flush_starts(self):
        pending,self._starts=self._starts,[]
        for b in pending:
            if not b.entity.destroyed and b.entity.active:b.call('start')
            elif not b.entity.destroyed:self._starts.append(b)
    def load_scene(self,path):
        self.assert_thread()
        if self.closed:raise RuntimeError('World is closed')
        self.pending_scene=asset_path(self.root,str(path))
    def reload_scene(self):self.load_scene(str(self.scene_path))
    def load(self,path,activate=True):
        self.assert_thread()
        if self.entities:raise RuntimeError('Use load_scene to replace a running scene')
        path=asset_path(self.root,str(path))
        def unique(pairs):
            out={}
            for k,v in pairs:
                if k in out:raise ValueError(f'Duplicate map key: {k}')
                out[k]=v
            return out
        data=json.loads(path.read_text(encoding='utf-8-sig'),object_pairs_hook=unique,
                        parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)))
        models=data['model']
        if not isinstance(models,list) or len(models)>self.MAX_ENTITIES:raise ValueError('model must be an array of <=4096 paths')
        n=len(models)
        def column(key,default):
            value=data.get(key,[default for _ in range(n)])
            if not isinstance(value,list) or len(value)!=n:raise ValueError(f'{key}: expected {n} entries')
            return value
        for key in ('positions','colors'):
            if key not in data:raise ValueError(f'Missing {key}')
        columns={key:column(key,None) for key in ('positions','colors','rotations','scales','textures','scripts','colliders','rigidbodies','names','layerSpacings','voxels','active','visible','rotations4D','scriptTrusted','castShadows','receiveShadows')}
        self.w_step=positive(data.get('layerSpacing',.1),'layerSpacing')
        from engine_runtime_options import normalized
        self.runtime=normalized(data.get('runtime'))
        self.title=str(data.get('title','MyEngine 2'));self.light_rotation.set(*vec(data.get('lightRotate')))
        self.camera.position=(0,2,7);self.camera.pitch=12;self.camera.yaw=0;self.camera.w=0
        self.camera.control_enabled=True
        camera=data.get('camera',{})
        self.camera.position=vec(camera.get('position'),(0,2,7))
        self.camera.pitch=camera.get('pitch',12);self.camera.yaw=camera.get('yaw',0);self.camera.w=camera.get('w',0)
        if 'collider' in camera:self.camera.collider=BoxCollider.from_json(camera['collider'])
        if camera.get('rigidbody') is not None:
            self.camera.add_rigidbody(**camera['rigidbody'])
        if 'freeFly' in camera:self.camera.control_enabled=bool(camera['freeFly'])
        if camera.get('controller'):self.camera.configure_physics(**camera['controller'])
        self.physics.configure(data.get('physics'))
        self.set_skybox(data.get('skybox'))
        self.set_sun(data.get('sun'))
        from engine_render import settings as shadow_settings
        self.shadows=shadow_settings(data.get('shadows'))
        self.voxel_boundary_bias=max(0,min(.001,finite(data.get('voxelBoundaryBias',1e-5))))
        self.resources.preload(models,columns['textures'],columns['voxels'])
        self._loading=True
        try:
            for i,model in enumerate(models):
                pos=columns['positions'][i]
                entity=self.instantiate(model,name=columns['names'][i] or f'entity_{i}',position=vec(pos),
                    rotation=vec(columns['rotations'][i]),scale=vec(columns['scales'][i],(1,1,1)),
                    color=vec(columns['colors'][i],(1,1,1),('r','g','b')),texture=columns['textures'][i],
                    scripts=columns['scripts'][i],collider=columns['colliders'][i],rigidbody=columns['rigidbodies'][i],
                    w=pos.get('w',0) if isinstance(pos,dict) else 0,layer_spacing=columns['layerSpacings'][i],voxels=columns['voxels'][i],
                    scale_w=columns['scales'][i].get('w',1) if isinstance(columns['scales'][i],dict) else 1,
                    rotation4=vec(columns['rotations4D'][i],keys=('xw','yw','zw')),trusted=columns['scriptTrusted'][i] is not False)
                entity.cast_shadows=columns['castShadows'][i] is not False;entity.receive_shadows=columns['receiveShadows'][i] is not False
                if columns['active'][i] is not None:entity.active=bool(columns['active'][i])
                if columns['visible'][i] is not None:entity.visible=bool(columns['visible'][i])
                entity.sync()
            # Prepare mesh acceleration while loading, so the first fixed step won't build terrain.
            for e in self.entities:
                if e.collider and e.collider.kind=='mesh':
                    for layer in e.layers:self.physics.geometry_for(layer)
                elif e.collider and e.collider.kind=='voxel':self.physics.voxel_geometry_for(e)
        finally:self._loading=False
        self.scene_path=path
        if data.get('ui'):
            from engine_ui import SlideUI
            self.ui=SlideUI(self,data['ui'])
        if activate:self.activate()
        self.log(f'Loaded {len(self.entities)} entities from {path.name}')
    def configure_runtime(self,**options):
        from engine_runtime_options import normalized,native_flags
        self.runtime=normalized(dict(self.runtime,**options))
        if hasattr(self.core,'runtime_flags'):self.core.runtime_flags.value=native_flags(self.runtime,self.editor_mode)
        self.core.set_title(self.title)
    def activate(self):
        self._submit();self.configure_runtime()
        if hasattr(self.core,'render_flags'):self.core.render_flags.value=1
        if self.editor_mode:self.camera.control_enabled=True
        else:
            self._flush_starts()
            if self.ui and self.ui.active:self.ui.actions(self.ui.slides[self.ui.active].get('onEnter',[]))
    def set_skybox(self,value):
        self.assert_thread()
        from engine_skybox import sky_settings,sky_paths
        settings=sky_settings(self.root,value)
        for path in sky_paths(self.root,settings):self.resources.texture(path)
        self.skybox=settings;self.skybox_failed=False
    def set_sun(self,value):
        from engine_skybox import sun_settings
        self.assert_thread();settings=sun_settings(value)
        if settings:self.resources.texture(settings['texture'])
        self.sun=settings;self.skybox_failed=False
    def load_ui(self,path):
        self.assert_thread()
        from engine_ui import SlideUI
        self.ui=SlideUI(self,path) if path else None
        if self.ui and self.ui.active:self.ui.actions(self.ui.slides[self.ui.active].get("onEnter",[]))
        return self.ui
    def save_png(self,path,data):
        self.assert_thread()
        if self.closed:raise RuntimeError('Cannot save a closed scene')
        from concurrent.futures import Future
        from PNGJSONUnitylity import json_data
        if len(self._screenshots)>=4:raise RuntimeError('Screenshot queue is full')
        # Freeze the developer-selected fields at the time of the request.
        value=json.loads(json.dumps(json_data(data),allow_nan=False));future=Future()
        self._screenshots.append((Path(path),value,future));return future
    def _finish_screenshots(self):
        if not self._screenshots:return
        from PNGJSONUnitylity import capture_rgba,encode_rgba,PNGJSONUnitylity
        jobs,self._screenshots=self._screenshots,[]
        try:pixels=capture_rgba()
        except Exception as ex:
            for _,_,future in jobs:
                if not future.cancelled():future.set_exception(ex)
            return
        pool=getattr(self.core,'save_pool',None)
        if pool is None:self.core.save_pool=pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='png-save')
        def save_batch():
            try:png=encode_rgba(*pixels)
            except Exception as ex:
                for _,_,future in jobs:
                    if not future.cancelled():future.set_exception(ex)
                return
            for path,data,future in jobs:
                if not future.set_running_or_notify_cancel():continue
                try:future.set_result(PNGJSONUnitylity.ToPngJson(path,data,png))
                except Exception as ex:future.set_exception(ex)
        pool.submit(save_batch)
    def draw(self):
        root=Path(__file__).resolve().parent
        if any(e.voxels for e in self.entities) and self.voxel_pass is None and not self.voxel_failed:
            try:
                from engine_voxels import VoxelPass
                self.voxel_pass=self.core.voxel_pass=VoxelPass(root)
            except Exception:self.voxel_failed=True;self.log('VOXEL RENDER ERROR');traceback.print_exc()
        if not self.render_failed:
            try:
                if self.scene_renderer is None:
                    from engine_render import SceneRenderer
                    self.scene_renderer=SceneRenderer(root)
                self.scene_renderer.draw(self,self.voxel_pass)
            except Exception:
                self.render_failed=True;self.log('SHADOW/SURFACE RENDER ERROR; reverting to native polygons');traceback.print_exc()
                if hasattr(self.core,'render_flags'):self.core.render_flags.value=0
        if (self.skybox or self.sun) and not self.skybox_failed:
            try:
                if self.skybox_pass is None:
                    from engine_skybox import SkyboxPass
                    self.skybox_pass=SkyboxPass(root)
                self.skybox_pass.draw(self)
            except Exception:self.skybox_failed=True;self.log('SKYBOX ERROR');traceback.print_exc()
        if self.voxel_pass and not self.voxel_failed:
            try:self.voxel_pass.draw(self)
            except Exception:self.voxel_failed=True;self.log('VOXEL RENDER ERROR');traceback.print_exc()
        if self.editor_mode and self.editor_outlines:
            from engine_gl import draw_selection
            for entity in self.entities:
                if entity.visible:draw_selection(entity,color=(1,1,1),width=3)
        if self.ui:self.ui.draw()
        self._finish_screenshots()
    def editor_tick(self,dt,keys):
        self.input.update(keys)
        self._flush_destroy()
        if self.input.pressed('Q'):self.camera.w-=self.w_step
        if self.input.pressed('E'):self.camera.w+=self.w_step
        self.light_rotation.y+=self.input.axis('F1','F2')*60*dt
        self.light_rotation.x+=self.input.axis('F3','F4')*60*dt
        self.light_rotation.z+=self.input.axis('F6','F7')*60*dt
        for e in self.entities:e.sync()

    def _fixed_update(self,dt):
        self.delta_time=dt
        if self.camera.controller:self.camera.controller.fixed_update(dt)
        for b in tuple(self.camera.scripts):b.call('fixed_update',dt)
        for e in tuple(self.entities):
            if e.active and not e.destroyed:
                for b in tuple(e.scripts):b.call('fixed_update',dt)
    def tick(self,dt,keys):
        self.assert_thread()
        if self.editor_mode:self.editor_tick(dt,keys);return
        dt=max(0.,min(.05,float(dt)));self.delta_time=dt;self.time+=dt
        blocked=self.ui.update(dt,self.core.pointer() if hasattr(self.core,'pointer') else None) if self.ui else False
        if hasattr(self.core,'runtime_flags'):
            from engine_runtime_options import native_flags
            flags=native_flags(self.runtime);self.core.runtime_flags.value=flags&~11 if blocked else flags
        self.input.update(bytes(256) if blocked else keys)
        self._flush_destroy();self._flush_starts()
        if self.camera.controller:self.camera.controller.update()
        for b in tuple(self.camera.scripts):b.call('update',dt)
        if self.runtime['wKeys'] and self.input.pressed('Q'):self.camera.w=round(self.camera.w-self.w_step,7)
        if self.runtime['wKeys'] and self.input.pressed('E'):self.camera.w=round(self.camera.w+self.w_step,7)
        if self.runtime['lightKeys']:
            self.light_rotation.y+=self.input.axis('F1','F2')*60*dt
            self.light_rotation.x+=self.input.axis('F3','F4')*60*dt
            self.light_rotation.z+=self.input.axis('F6','F7')*60*dt
        if self.runtime['scriptReload'] and self.input.pressed('F5'):
            for e in (*self.entities,self.camera):
                for b in tuple(e.scripts):
                    if b.reload(defer_start=True):self._starts.append(b)
            self._flush_starts()
        for e in tuple(self.entities):
            if e.active and not e.destroyed:
                for b in tuple(e.scripts):b.call('update',dt)
            e.sync()
        self._flush_starts()
        try:self.physics.tick(dt,self._fixed_update)
        finally:self.delta_time=dt
        self._flush_destroy()
        for e in self.entities:e.sync()
        if self.runtime['diagnosticTitle'] and self.time>=self._next_title:
            self._next_title=self.time+.2;l=self.light_rotation
            self.core.set_title(f'{self.title} | {len(self.entities)} objects | W={self.camera.w:.2f} | Light {l.x:.0f},{l.y:.0f},{l.z:.0f}')
    def shutdown(self,clear_scene=True):
        if self.closed:return
        self.closed=True
        for _,_,future in self._screenshots:
            if not future.cancelled():future.set_exception(RuntimeError('Scene closed before screenshot'))
        self._screenshots.clear()
        if clear_scene:
            self.core.clear()
            if hasattr(self.core,'render_flags'):self.core.render_flags.value=0
        for e in tuple(self.entities):
            for b in e.scripts:b.call('on_destroy',force=True);sys.modules.pop(b.module_name,None)
            e.release_slice();e.destroyed=True
        for b in self.camera.scripts:b.call('on_destroy',force=True);sys.modules.pop(b.module_name,None)
        if self.scene_renderer:self.scene_renderer.close();self.scene_renderer=None
        self.slice_jobs.close()
        self.camera.destroyed=True
        if clear_scene and self.voxel_pass:self.voxel_pass.close();self.core.voxel_pass=None
        self.voxel_pass=None
        if self.skybox_pass:self.skybox_pass.close();self.skybox_pass=None
        self.physics.close();self.resources.close();self.entities.clear();self.by_name.clear()
        if clear_scene:
            self.core.resource_cache.close()
            if hasattr(self.core,'save_pool'):self.core.save_pool.shutdown(wait=True);del self.core.save_pool
        self._starts.clear();self._destroy.clear()


_world=None
_editor=None

def switch_scene(world,path):
    """Stage first; a failed parse/asset load restores the previous running world."""
    core=world.core;saved_camera=tuple(core.camera);saved_light=tuple(core.light);saved_control=core.camera_control.value
    candidate=None
    try:
        candidate=World(core,world.root);candidate.load(path,activate=False)
        next_camera=tuple(core.camera);next_light=tuple(core.light);next_control=core.camera_control.value
    except Exception:
        if candidate is not None:candidate.shutdown(clear_scene=False)
        for i,v in enumerate(saved_camera):core.camera[i]=v
        core.light.set(*saved_light);core.camera_control.value=saved_control
        world._submit();world.log('SCENE LOAD FAILED:',path);traceback.print_exc()
        return world
    world.shutdown(clear_scene=False)
    for i,v in enumerate(next_camera):core.camera[i]=v
    core.light.set(*next_light);core.camera_control.value=next_control
    candidate.editor_outlines=world.editor_outlines
    candidate.input.current=world.input.current
    candidate.input.previous=world.input.current
    global _world
    if _world is world:_world=candidate
    candidate.activate()
    return candidate


def start():
    global _world,_editor
    core=NativeCore();args=core.arguments()
    root=Path(__file__).resolve().parent
    if '--project' in args:
        i=args.index('--project');root=Path(args[i+1]).resolve();args=args[:i]+args[i+2:]
    core.editor_mode='--editor' in args
    if core.editor_mode:
        from engine_editor_link import RuntimeEditor
        i=args.index('--editor')
        _editor=RuntimeEditor(core,args[i+1],args[i+2])
        args=args[:i]
    os.chdir(root)
    if str(root) not in sys.path:sys.path.insert(1,str(root))
    _world=World(core,root)
    default='map.json'
    manifest=root/'build.json'
    if manifest.is_file():default=json.loads(manifest.read_text(encoding='utf-8'))['mainScene']
    _world.load(_world.root/(args[0] if args else default))


def frame():
    global _world
    if _editor is not None:_world=_editor.process(_world)
    _world.tick(_world.core.delta.value,_world.core.keys)
    if _world.pending_scene is not None:
        path=_world.pending_scene;_world.pending_scene=None
        _world=switch_scene(_world,path)


def draw():
    if _world is not None:
        _world.draw()
        if _editor is not None and _world.editor_mode and _editor.selected:
            entity=_world.find(_editor.selected)
            if entity is not None and not entity.is_player:
                from engine_gl import draw_selection
                draw_selection(entity)
        if _editor is not None:_editor.gizmo.frame(_world)

def shutdown():
    if _editor is not None:_editor.close()
    if _world is not None:_world.shutdown()
