"""World snapshots in screenshot PNGs. I/O/compression run in the shared save worker."""
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import base64
import json
import math
import zlib
from engine_scene import SceneDocument, DEFAULTS
from PNGJSONUnitylity import PNGJSONUnitylity, LIMIT

STATES=('idle','saving','saved','loading','loaded','error')


def project_ref(root, value):
    if value is None or value=='':return None
    root=Path(root).resolve();path=(root/str(value)).resolve()
    try:return path.relative_to(root).as_posix()
    except ValueError:raise ValueError('Save asset must be inside this project: '+str(value)) from None


def collider_data(c):
    if c is None:return None
    return {'type':c.kind,'size':c.size,'center':c.center,'isTrigger':c.is_trigger,'enabled':c.enabled,
            'wSize':c.w_size,'layer':c.layer,'mask':c.mask,'friction':c.friction,'restitution':c.restitution}


def body_data(body):
    if body is None:return None
    return {**{key:getattr(body,key) for key in ('mass','is_kinematic','freeze_rotation','use_gravity','gravity_scale',
                 'linear_damping','angular_damping','friction','restitution')},
            'velocity':list(body.velocity),'angular_velocity':list(body.angular_velocity)}


def script_data(world,entity):
    result=[]
    for binding in entity.scripts:
        save=getattr(binding.instance,'save_state',None)
        state=save() if callable(save) else None
        # Fail on non-JSON state while still on the owner thread; never retain live objects.
        state=json.loads(json.dumps(state,allow_nan=False))
        result.append({'path':project_ref(world.root,binding.path),'state':state,
                       'enabled':bool(binding.enabled and getattr(binding.instance,'enabled',True))})
    return result


@dataclass
class FrozenSave:
    data: dict
    voxels: list

    def encode(self):
        data=deepcopy(self.data)
        for index,size,cell,pixels,enabled,width in self.voxels:
            data['scene']['voxels'][index]={'snapshot':{'size':size,'cellSize':cell,
                'rgbaZlib':base64.b64encode(zlib.compress(pixels,3)).decode('ascii')},'enabled':enabled,'wSize':width}
        if len(json.dumps(data,ensure_ascii=False,allow_nan=False).encode('utf-8'))>LIMIT:
            raise ValueError('World save exceeds the PNG JSON limit of 8 MiB')
        return data


def snapshot(world):
    world.assert_thread()
    base=deepcopy(getattr(world,'_scene_data',{}))
    count=len(base.get('model',[]))
    for key in list(base):
        if isinstance(base[key],list) and len(base[key])==count and key!='buildKeepAssets':base.pop(key)
    for key in DEFAULTS:base[key]=[]
    states={};voxels=[];voxel_bytes=0
    for entity in world.entities:
        if entity.destroyed:continue
        position=dict(zip('xyz',entity.position));position['w']=entity.w
        scale=dict(zip('xyz',entity.scale));scale['w']=entity.scale_w
        scripts=script_data(world,entity);states[entity.name]=scripts
        row={'model':project_ref(world.root,entity.model),'positions':position,'rotations':dict(zip('xyz',entity.rotation)),
             'scales':scale,'colors':dict(zip('rgb',entity.color)),'names':entity.name,'textures':project_ref(world.root,entity.texture),
             'scripts':[entry['path'] for entry in scripts],'colliders':collider_data(entity.collider),'rigidbodies':body_data(entity.rigidbody),
             'rotations4D':dict(zip(('xw','yw','zw'),entity.rotation4)),'layerSpacings':entity.layer_spacing,'voxels':None,
             'active':entity.active,'visible':entity.visible,'scriptTrusted':entity.script_trusted,
             'castShadows':entity.cast_shadows,'receiveShadows':entity.receive_shadows,
             'materials':deepcopy(entity.material),'lights':deepcopy(entity.light),
             'liquids':deepcopy(entity.liquid.config) if entity.liquid else None}
        if entity.voxels:
            v=entity.voxels;g=v.grid
            voxel_bytes+=len(g.pixels)
            if voxel_bytes>256*1024*1024:raise ValueError('Voxel snapshot exceeds 256 MiB decoded')
            voxels.append((len(base['model']),g.size,g.cell_size,bytes(g.pixels),v.enabled,v.w_size))
        for key,default in DEFAULTS.items():base[key].append(deepcopy(row.get(key,default)))
    c=world.camera;states['player']=script_data(world,c)
    camera={'position':dict(zip('xyz',c.position)),'pitch':c.pitch,'yaw':c.yaw,'w':c.w,
            'freeFly':c.control_enabled,'collider':collider_data(c.collider),'rigidbody':body_data(c.rigidbody),
            'scripts':[entry['path'] for entry in states['player']]}
    if c.controller:
        controller=c.controller
        camera['controller']={'mode':controller.mode,'size':c.collider.size,'center':c.collider.center,
                              'mass':c.rigidbody.mass if c.rigidbody else 75,'speed':controller.speed,
                              'sprint':controller.sprint,'jump':controller.jump_speed}
        if controller.mode=='script':camera['controller']['script']=camera['scripts'][0]
        camera['savedBody']=camera.pop('rigidbody')
    base.update(camera=camera,lighting=deepcopy(world.lighting),lightRotate=dict(zip('xyz',world.light_rotation)),
                shadows=deepcopy(world.shadows),reflections=deepcopy(getattr(world,'reflections',{})),
                skybox=deepcopy(world.skybox),sun=deepcopy(world.sun),runtime=deepcopy(world.runtime),title=world.title)
    return FrozenSave({'kind':'MyEngine.World','version':1,'sourceScene':project_ref(world.root,getattr(world,'scene_identity',None) or world.scene_path),
                       'scene':base,'scripts':states,'time':world.time},voxels)


def read_world(path,root):
    data=PNGJSONUnitylity.FromPngJson(path)
    if not isinstance(data,dict) or data.get('kind')!='MyEngine.World' or data.get('version')!=1:
        raise ValueError('PNG is not a MyEngine world save')
    source=project_ref(root,data['sourceScene'])
    if not source or not (Path(root)/source).is_file():raise ValueError('Source scene is missing from this project')
    scene=SceneDocument(data['scene']).data
    states=data.get('scripts',{})
    if not isinstance(states,dict):raise ValueError('Invalid saved script states')
    for name,entries in states.items():
        if not isinstance(name,str) or not isinstance(entries,list):raise ValueError('Invalid saved script binding')
        for entry in entries:
            if not isinstance(entry,dict) or not isinstance(entry.get('path'),str):raise ValueError('Invalid saved script path')
            project_ref(root,entry['path'])
    for key in ('model','textures'):
        for value in scene[key]:project_ref(root,value)
    for scripts in [*scene['scripts'],scene.get('camera',{}).get('scripts',[])]:
        for value in ([scripts] if isinstance(scripts,str) else scripts or []):project_ref(root,value)
    camera=scene.get('camera',{});project_ref(root,camera.get('controller',{}).get('script'))
    project_ref(root,scene.get('ui'))
    total=0
    from engine_voxels import VoxelGrid,VoxelRenderer
    for index,value in enumerate(scene['voxels']):
        if value is None:continue
        if not isinstance(value,dict) or 'snapshot' not in value:raise ValueError('World PNG requires embedded voxel state')
        raw=value['snapshot'];grid=VoxelGrid(raw['size'],raw['cellSize']);expected=math.prod(grid.size)*4
        total+=expected
        if total>256*1024*1024:raise ValueError('Voxel snapshot exceeds 256 MiB decoded')
        compressed=base64.b64decode(raw['rgbaZlib'],validate=True);decoder=zlib.decompressobj()
        pixels=decoder.decompress(compressed,expected+1)
        if len(pixels)!=expected or not decoder.eof or decoder.unused_data:raise ValueError('Invalid voxel snapshot size')
        grid._storage.pixels[:]=pixels
        width=value.get('wSize')
        if width is not None and (not isinstance(width,(int,float)) or not math.isfinite(width) or width<=0):raise ValueError('Invalid voxel W size')
        scene['voxels'][index]=VoxelRenderer(grid,bool(value.get('enabled',True)),width)
    # Keep decoded grid objects separate from ordinary scene JSON; all decoding happened off-thread.
    data['scene']=scene;data['sourceScene']=source
    return data


class SaveSystem:
    def __init__(self,world):self.world=world;self.records={};self.pending=None
    def state(self,key='save'):return self.records.get(str(key),{}).get('state','idle')
    def error(self,key='save'):return self.records.get(str(key),{}).get('error','')
    def _path(self,path):
        root=self.world.root;relative=project_ref(root,path)
        if not relative or Path(relative).suffix.lower()!='.png':raise ValueError('Save path must be a PNG inside the project')
        return root/relative
    def _pool(self):
        from concurrent.futures import ThreadPoolExecutor
        if not hasattr(self.world.core,'save_pool'):
            self.world.core.save_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='png-save')
        return self.world.core.save_pool
    def request_save(self,path='saves/slot1.png',key='save'):
        self.world.assert_thread();key=str(key)
        if self.state(key) in ('saving','loading'):return False
        try:
            path=self._path(path)
            if len(self.world._screenshots)>=4:raise RuntimeError('Screenshot queue is full')
            frozen=snapshot(self.world)
            from concurrent.futures import Future
            future=Future();self.world._screenshots.append((path,frozen,future))
            self.records[key]={'state':'saving','future':future,'path':path};return True
        except Exception as ex:self.records[key]={'state':'error','error':str(ex)};self.world.log('PNG SAVE:',ex);return False
    def request_load(self,path='saves/slot1.png',key='save'):
        self.world.assert_thread();key=str(key);self.poll()
        if self.pending is not None or self.state(key) in ('saving','loading'):return False
        try:
            path=self._path(path)
            if any(r.get('state')=='saving' and r.get('path')==path for r in self.records.values()):raise RuntimeError('This PNG save is still being written')
            future=self._pool().submit(read_world,path,self.world.root)
            self.pending=(key,future);self.records[key]={'state':'loading','path':path};return True
        except Exception as ex:self.records[key]={'state':'error','error':str(ex)};self.world.log('PNG LOAD:',ex);return False
    def poll(self):
        for key,record in self.records.items():
            future=record.get('future')
            if future is not None and future.done():
                record.pop('future')
                try:future.result();record['state']='saved'
                except Exception as ex:record.update(state='error',error=str(ex));self.world.log('PNG SAVE:',ex)
    def finish(self):
        self.poll();world=self.world
        if self.pending is None or not self.pending[1].done():return world
        key,future=self.pending;self.pending=None
        try:
            data=future.result()
            from engine_runtime import switch_scene
            candidate=switch_scene(world,data['sourceScene'],saved=data)
            if candidate is world:raise RuntimeError('World restore failed; the current game was kept')
            candidate.saves.records={k:{a:b for a,b in r.items() if a!='future'} for k,r in self.records.items()}
            candidate.saves.records[key]={'state':'loaded'}
            return candidate
        except Exception as ex:
            self.records[key]={'state':'error','error':str(ex)};world.log('PNG LOAD:',ex);return world
    def close(self):
        if self.pending:self.pending[1].cancel();self.pending=None


def restore_scripts(world,states):
    """Resume bindings without replaying Start spawners. Optional data hooks run on owner thread."""
    world._starts.clear()
    for entity in [*world.entities,world.camera]:
        entries=states.get(entity.name,[])
        for binding in entity.scripts:
            path=project_ref(world.root,binding.path)
            entry=next((r for r in entries if r['path']==path),{})
            binding.started=True;binding.enabled=bool(entry.get('enabled',True))
            if world.ui:world.ui.bind_blueprint(binding)
            if entry.get('state') is not None:binding.call('load_state',entry['state'])
            binding.call('on_restore')
