"""Prefabs are data-only scene fragments. Spawn atomically without changing the scene."""
from pathlib import Path
from copy import deepcopy
import json
from engine_scene import SceneDocument,atomic_json
from engine_assets import finite

def load_prefab(path):
 p=Path(path)
 if p.stat().st_size>16*1024*1024:raise ValueError('Prefab exceeds 16 MiB')
 data=json.loads(p.read_text(encoding='utf-8-sig'))
 if data.get('format')!=1 or data.get('kind')!='prefab':raise ValueError('Not a prefab')
 scene=SceneDocument(data['scene'])
 if len(scene.data['model'])>1024:raise ValueError('Prefab limit: 1024 objects')
 return scene.data

def save_prefab(path,document,indices):
 data=deepcopy(document.data);ids=sorted(set(indices))
 if not ids or any(i<0 or i>=len(data['model']) for i in ids):raise ValueError('Select objects first')
 columns=document.columns();scene={k:[deepcopy(data[k][i]) for i in ids] for k in columns}
 # First selected object is the origin. All transforms in the prefab are relative to it.
 origin=data['positions'][ids[0]] or {};origin=[origin.get(k,0) for k in ('x','y','z','w')] if isinstance(origin,dict) else [*origin,0]
 for i,p in enumerate(scene['positions']):
  p=p or {};p={k:p.get(k,0) for k in ('x','y','z','w')} if isinstance(p,dict) else dict(zip(('x','y','z','w'),[*p,0]))
  scene['positions'][i]={k:p[k]-origin[j] for j,k in enumerate(('x','y','z','w'))}
 atomic_json(path,{'format':1,'kind':'prefab','scene':scene})

def append_prefab(document,data,position=(0,0,0),prefix=None):
 source=SceneDocument(data);before=deepcopy(document.data);added=[]
 if len(document.data['model'])+len(source.data['model'])>4096:raise ValueError('Scene entity capacity exceeded')
 try:
  for i in range(len(source.data['model'])):
   row={k:deepcopy(source.data[k][i]) for k in source.columns()};name=document.unique_name((prefix+' ' if prefix else '')+(row['names'] or 'Prefab'))
   p=row['positions'] or {};p={k:p.get(k,0) for k in ('x','y','z','w')} if isinstance(p,dict) else dict(zip(('x','y','z'),p))
   for k,v in zip(('x','y','z'),position):p[k]=p.get(k,0)+finite(v)
   row['positions']=p;row['names']=name
   n=len(document.data['model'])
   for k in source.columns():
    if k not in document.data:document.data[k]=[None]*n
   for k in document.columns():document.data[k].append(deepcopy(row.get(k)))
   added.append(n)
  document.validate();document.undo_stack.append(before);document.undo_stack=document.undo_stack[-64:];document.redo_stack.clear();return added
 except Exception:document.data=before;raise

def instantiate_prefab(world,path,position=(0,0,0),*,prefix=None,trusted=True):
 from engine_assets import asset_path
 from engine_runtime import vec
 data=load_prefab(asset_path(world.root,path));created=[];was_loading=world._loading;world._loading=True
 try:
  for i,model in enumerate(data['model']):
   p=data['positions'][i] or {};pos=vec(p);name=(prefix+' ' if prefix else '')+data['names'][i];base=name;j=1
   while world.find(name):name=base+' '+str(j);j+=1
   scale=data['scales'][i] or {};e=world.instantiate(model,name=name,position=tuple(a+finite(b) for a,b in zip(pos,position)),rotation=vec(data['rotations'][i]),scale=vec(scale,(1,1,1)),color=vec(data['colors'][i],(1,1,1),('r','g','b')),texture=data['textures'][i],scripts=data['scripts'][i],collider=data['colliders'][i],rigidbody=data['rigidbodies'][i],w=p.get('w',0) if isinstance(p,dict) else 0,layer_spacing=data['layerSpacings'][i],voxels=data['voxels'][i],scale_w=scale.get('w',1) if isinstance(scale,dict) else 1,rotation4=vec(data['rotations4D'][i],keys=('xw','yw','zw')),trusted=trusted and bool(data['scriptTrusted'][i]),liquid=data['liquids'][i],light=data['lights'][i])
   from engine_materials import material_settings
   created.append(e);e.active=bool(data['active'][i]);e.visible=bool(data['visible'][i]);e.cast_shadows=bool(data['castShadows'][i]);e.receive_shadows=bool(data['receiveShadows'][i]);e.material=material_settings(data['materials'][i]);e.sync()
  return created
 except Exception:
  for e in created:world.destroy(e)
  world._flush_destroy();raise
 finally:
  world._loading=was_loading
  if not was_loading:world._submit()
