"""Light components and a bounded render-system snapshot. Signed linear RGB is intentional."""
import colorsys
import math
from engine_assets import finite
from engine_collision import rotation_axes

MAX_LIGHTS = 16


def triple(value, default=(1., 1., 1.)):
    if value is None:return tuple(default)
    if isinstance(value, dict):value=[value.get(k, default[i]) for i,k in enumerate('rgb')]
    if len(value)!=3:raise ValueError('Light color requires three values')
    return tuple(finite(v) for v in value)


def temperature_rgb(kelvin):
    """Approximate blackbody display RGB, converted to linear light."""
    t=max(1000.,min(40000.,finite(kelvin)))/100.
    r=255. if t<=66 else 329.698727446*(t-60)**-.1332047592
    g=99.4708025861*math.log(t)-161.1195681661 if t<=66 else 288.1221695283*(t-60)**-.0755148492
    b=255. if t>=66 else 0. if t<=19 else 138.5177312231*math.log(t-10)-305.0447927307
    def linear(x):
        x=max(0.,min(1.,x/255.));return x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4
    return tuple(linear(v) for v in (r,g,b))


def light_settings(value=None):
    if value is None:return None
    if not isinstance(value,dict):raise ValueError('Light must be a JSON object or null')
    d=dict(value);kind=str(d.get('type','point')).lower()
    if kind not in ('directional','point','spot'):raise ValueError('Light type: directional, point or spot')
    mode=str(d.get('colorMode','rgb')).lower()
    if mode not in ('rgb','hsv','temperature'):raise ValueError('Light colorMode: rgb, hsv or temperature')
    intensity=finite(d.get('intensity',1));distance=finite(d.get('range',10))
    inner=finite(d.get('innerAngle',25));outer=finite(d.get('outerAngle',45))
    temperature=finite(d.get('temperature',6500));hsv=tuple(d.get('hsv',(0,1,1)))
    if len(hsv)!=3:raise ValueError('HSV requires H degrees, S and V')
    hsv=tuple(finite(v) for v in hsv)
    if not 0<=hsv[1]<=1 or hsv[2]<0:raise ValueError('HSV: S 0..1 and V >= 0')
    if not .001<=distance<=1e6 or not 0<=inner<=outer<179 or outer<=0:raise ValueError('Light range > 0; 0 <= innerAngle <= outerAngle < 179')
    if not 1000<=temperature<=40000:raise ValueError('Temperature: 1000..40000 K')
    return {'type':kind,'enabled':bool(d.get('enabled',True)),'colorMode':mode,
            'color':list(triple(d.get('color'))),'hsv':list(hsv),'temperature':temperature,
            'intensity':intensity,'range':distance,'innerAngle':inner,'outerAngle':outer,
            'shadows':bool(d.get('shadows',kind=='directional'))}


def light_color(light):
    mode=light['colorMode']
    if mode=='temperature':rgb=temperature_rgb(light['temperature'])
    elif mode=='hsv':h,s,v=light['hsv'];rgb=colorsys.hsv_to_rgb((h%360)/360,s,v)
    else:rgb=light['color']
    return tuple(v*light['intensity'] for v in rgb)


def lighting_settings(value=None):
    d=dict(value or {});legacy=str(d.get('legacy','auto'))
    if legacy not in ('auto','on','off'):raise ValueError('Legacy sun: auto, on, off')
    return {'ambient':list(triple(d.get('ambient'),(.2,.2,.2))),'legacy':legacy}


def collect(world):
    """Nearest local lights plus directional lights, stable order, at most 16 GPU lights."""
    configuration=getattr(world,'lighting',None) or lighting_settings()
    present=[e for e in world.entities if not e.destroyed and getattr(e,'light',None) is not None]
    candidates=[];camera=tuple(world.camera.position)
    for index,e in enumerate(present):
        light=e.light
        if not e.active or not light['enabled']:continue
        direction=rotation_axes(tuple(e.rotation))[2]  # light travels along local +Z
        score=-1. if light['type']=='directional' else sum((a-b)**2 for a,b in zip(e.position,camera))
        candidates.append((score,index,{'type':light['type'],'position':tuple(e.position),'direction':direction,
            'color':light_color(light),'range':light['range'],'inner':math.cos(math.radians(light['innerAngle']*.5)),
            'outer':math.cos(math.radians(light['outerAngle']*.5)),'shadows':light['shadows']}))
    legacy=configuration['legacy']=='on' or configuration['legacy']=='auto' and not present
    rows=[r[2] for r in sorted(candidates,key=lambda r:r[:2])[:MAX_LIGHTS]]
    shadow=next((i for i,r in enumerate(rows) if r['type']=='directional' and r['shadows']),-1)
    direction=rotation_axes(tuple(world.light_rotation))[1] if shadow<0 else tuple(-x for x in rows[shadow]['direction'])
    return {'lights':rows,'ambient':configuration['ambient'],'legacy':legacy,'shadow':shadow,'direction':direction}


def contribution(light, position, normal):
    """CPU reference for attenuation and the signed GPU lighting calculation."""
    if light['type']=='directional':l=tuple(-v for v in light['direction']);attenuation=1.
    else:
        delta=tuple(a-b for a,b in zip(light['position'],position));distance=math.sqrt(sum(v*v for v in delta))
        l=tuple(v/max(distance,1e-8) for v in delta)
        attenuation=max(0.,1-distance/light['range'])**2
        if light['type']=='spot':
            cosine=-sum(a*b for a,b in zip(l,light['direction']))
            t=max(0.,min(1.,(cosine-light['outer'])/max(1e-5,light['inner']-light['outer'])))
            attenuation*=t*t*(3-2*t)
    return tuple(c*attenuation*max(0.,sum(a*b for a,b in zip(normal,l))) for c in light['color'])


def upload(renderer,program,world):
    frame=getattr(world,'_light_frame',None) or collect(world)
    renderer.i(program,'lightCount',len(frame['lights']));renderer.i(program,'legacyLight',int(frame['legacy']))
    renderer.i(program,'shadowLight',frame['shadow']);renderer.v(program,'ambientLight',frame['ambient'])
    renderer.v(program,'lightDirection',frame['direction'])
    gl=renderer.gl
    from engine_gl import I,F
    for i,light in enumerate(frame['lights']):
        renderer.v(program,'lampPosition[%d]'%i,light['position']);renderer.v(program,'lampDirection[%d]'%i,light['direction'])
        renderer.v(program,'lampColor[%d]'%i,light['color'])
        gl.fn('glUniform4f',None,I,F,F,F,F)(renderer.loc(program,'lampData[%d]'%i),
            {'directional':0,'point':1,'spot':2}[light['type']],light['range'],light['inner'],light['outer'])
