"""Metallic material settings and bounds used for reflection capture culling."""
import math
from engine_assets import finite
from engine_collision import rotation_axes

def material_settings(value=None):
    if value is not None and not isinstance(value,dict):raise ValueError('Material must be an object')
    value=value or {};out={}
    for key,default in (('metallic',0.),('roughness',.3),('reflectionStrength',.65)):
        if isinstance(value.get(key,default),bool):raise ValueError(key+' must be a number')
        out[key]=finite(value.get(key,default))
        if not 0<=out[key]<=1:raise ValueError(key+' must be between 0 and 1')
    mode=str(value.get('mode','opaque')).lower()
    if mode not in ('opaque','cutout','transparent'):raise ValueError('Material mode: opaque, cutout, transparent')
    out['mode']=mode
    for key,default,maximum in (('opacity',1.,1.),('alphaCutoff',.1,1.),('voxelDensity',1.,100.)):
        out[key]=finite(value.get(key,default))
        if not 0<=out[key]<=maximum:raise ValueError(key+' outside its allowed range')
    out['twoSided']=bool(value.get('twoSided',True))
    return out

def reflection_settings(value=None):
    if value is not None and not isinstance(value,dict):raise ValueError('Reflections must be an object')
    value=value or {};enabled=value.get('enabled',True);count=value.get('maxObjects',8)
    if type(enabled) is not bool or type(count) is not int or not 0<=count<=8:raise ValueError('Reflections: enabled boolean, maxObjects 0..8')
    distance=finite(value.get('distance',40))
    if not 1<=distance<=500:raise ValueError('Reflection distance: 1..500')
    size=value.get('size',256);faces=value.get('facesPerFrame',1);draws=value.get('maxDraws',128)
    interval=finite(value.get('updateInterval',.05))
    if type(size) is not int or size not in (64,128,256,512):raise ValueError('Reflection size: 64 / 128 / 256 / 512')
    if type(faces) is not int or not 1<=faces<=6:raise ValueError('Reflection facesPerFrame: 1..6')
    if type(draws) is not int or not 1<=draws<=512:raise ValueError('Reflection maxDraws: 1..512')
    if not 0<=interval<=5:raise ValueError('Reflection updateInterval: 0..5 seconds')
    return {'enabled':enabled,'maxObjects':count,'distance':distance,'size':size,'facesPerFrame':faces,'maxDraws':draws,'updateInterval':interval}

def world_bounds(entity):
    if entity.voxels:
        grid=entity.voxels.grid;lo=tuple(-n*grid.cell_size*.5 for n in grid.size);hi=tuple(-v for v in lo)
    elif entity.layers and entity.layer is not None:
        layer=entity.layers[entity.layer];lo=layer.minimum;hi=layer.maximum
    else:return None
    axes=rotation_axes(tuple(entity.rotation));scale=tuple(entity.scale);position=tuple(entity.position)
    center=tuple((lo[i]+hi[i])*.5 for i in range(3));half=tuple((hi[i]-lo[i])*.5 for i in range(3))
    world_center=tuple(position[k]+sum(axes[i][k]*scale[i]*center[i] for i in range(3)) for k in range(3))
    extent=tuple(sum(abs(axes[i][k]*scale[i])*half[i] for i in range(3)) for k in range(3))
    return tuple(world_center[k]-extent[k] for k in range(3)),tuple(world_center[k]+extent[k] for k in range(3))

def reflection_proxies(entities,camera,settings):
    if not settings['enabled'] or settings['maxObjects']==0:return []
    candidates=[]
    for index,e in enumerate(entities):
        if e.destroyed or not e.active or not e.visible:continue
        if not e.voxels and not e._native.visible:continue
        bounds=world_bounds(e)
        if bounds is None:continue
        lo,hi=bounds;distance=sum(max(lo[k]-camera[k],0,camera[k]-hi[k])**2 for k in range(3))
        if distance>settings['distance']**2:continue
        candidates.append((distance,index,e,lo,hi,tuple(e.color)))
    return [(e,lo,hi,color) for _,_,e,lo,hi,color in sorted(candidates,key=lambda v:v[:2])[:settings['maxObjects']]]

def ray_box(origin,direction,minimum,maximum):
    """CPU reference for the shader slab intersection."""
    near=-math.inf;far=math.inf
    for o,d,lo,hi in zip(origin,direction,minimum,maximum):
        if abs(d)<1e-8:
            if o<lo or o>hi:return None
        else:
            a,b=sorted(((lo-o)/d,(hi-o)/d));near=max(near,a);far=min(far,b)
    if far<max(near,0):return None
    return near if near>.001 else far if far>.001 else None


def transparent(entity):
    return (getattr(entity,'material',None) or {}).get('mode')=='transparent'

def transparent_order(entities,camera):
    return sorted((e for e in entities if not e.destroyed and e.active and e.visible and transparent(e)),
                  key=lambda e:sum((a-b)**2 for a,b in zip(e.position,camera)),reverse=True)
