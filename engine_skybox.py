"""Sky at far depth: equirectangular PNG/BMP or six named cube faces."""
from pathlib import Path
import json
import ctypes as C
from engine_gl import GL,F,I,U,P,inverse,multiply
from engine_assets import asset_path,finite

FACES=('px','nx','py','ny','pz','nz')

def sky_settings(root,value):
    if not value:return None
    if isinstance(value,str):
        if value.lower().endswith('.json'):
            value=json.loads(asset_path(Path(root),value).read_text(encoding='utf-8-sig'))
        else:value={'texture':value}
    if not isinstance(value,dict):raise ValueError('skybox must be a path or object')
    d=dict(value);d['yaw']=finite(d.get('yaw',0));d['exposure']=finite(d.get('exposure',1))
    if not 0<=d['exposure']<=16:raise ValueError('Sky exposure must be in 0..16')
    if 'faces' in d:
        if set(d['faces'])!=set(FACES):raise ValueError('Sky faces: px nx py ny pz nz required')
    elif not d.get('texture'):raise ValueError('Sky needs texture or six faces')
    return d

def sky_paths(root,value):
    d=sky_settings(root,value)
    if not d:return []
    return list(d['faces'].values()) if 'faces' in d else [d['texture']]

class SkyboxPass:
    def __init__(self,root,gl=None):
        self.gl=gl or GL();self.program=self.gl.compile((Path(root)/'shaders/voxel.vert').read_text(),(Path(root)/'shaders/skybox.frag').read_text())
        self.uniforms={n:self.gl.fn('glGetUniformLocation',I,U,C.c_char_p)(self.program,n.encode()) for n in ('inverseViewProjection','viewport','cameraPosition','yaw','exposure','cubeMode','sky0','sky1','sky2','sky3','sky4','sky5','hasSky','sunTexture','hasSun','sunDirection','sunSize','sunBrightness','blackAsAlpha')}
    def draw(self,world):
        s=world.skybox;sun=getattr(world,'sun',None)
        if not s and not sun:return
        has_sky=bool(s);s=s or {'yaw':0,'exposure':1}
        gl=self.gl;view=(F*16)();proj=(F*16)();viewport=(I*4)();previous=I()
        gl.fn('glGetFloatv',None,U,P)(0x0BA6,view);gl.fn('glGetFloatv',None,U,P)(0x0BA7,proj)
        gl.fn('glGetIntegerv',None,U,P)(0x0BA2,viewport);gl.fn('glGetIntegerv',None,U,P)(0x8B8D,C.byref(previous))
        paths=[s['faces'][f] for f in FACES] if 'faces' in s else [s.get('texture')]*6
        # Resolve before touching GL state; resources are cached and owned by this world.
        textures=[world.resources.texture(p) if p else 0 for p in paths]
        sun_texture=world.resources.texture(sun['texture']) if sun else 0
        gl.fn('glPushAttrib',None,U)(0xfffff)
        try:
            gl.fn('glUseProgram',None,U)(self.program)
            for cap in (0x0B50,0x0BE2,0x0BC0,0x0B44):gl.fn('glDisable',None,U)(cap)
            gl.fn('glEnable',None,U)(0x0B71);gl.fn('glDepthFunc',None,U)(0x0203);gl.fn('glDepthMask',None,C.c_ubyte)(0)
            for i,texture in enumerate(textures):
                gl.fn('glActiveTexture',None,U)(0x84C0+i);gl.fn('glBindTexture',None,U,U)(0x0DE1,texture)
                gl.fn('glUniform1i',None,I,I)(self.uniforms['sky'+str(i)],i)
            gl.fn('glUniform1i',None,I,I)(self.uniforms['hasSky'],int(has_sky))
            gl.fn('glUniform1i',None,I,I)(self.uniforms['hasSun'],int(bool(sun)))
            if sun:
                from engine_collision import rotation_axes
                gl.fn('glActiveTexture',None,U)(0x84C6);gl.fn('glBindTexture',None,U,U)(0x0DE1,sun_texture)
                gl.fn('glUniform1i',None,I,I)(self.uniforms['sunTexture'],6)
                gl.fn('glUniform3f',None,I,F,F,F)(self.uniforms['sunDirection'],*(getattr(world,'_light_frame',None) or {}).get('direction',rotation_axes(tuple(world.light_rotation))[1]))
                gl.fn('glUniform1f',None,I,F)(self.uniforms['sunSize'],sun['size']*0.017453292519943295)
                gl.fn('glUniform1f',None,I,F)(self.uniforms['sunBrightness'],sun['brightness'])
                gl.fn('glUniform1i',None,I,I)(self.uniforms['blackAsAlpha'],int(sun['blackAsAlpha']))
            gl.fn('glUniform1i',None,I,I)(self.uniforms['cubeMode'],int('faces' in s))
            gl.fn('glUniform1f',None,I,F)(self.uniforms['yaw'],s['yaw']*0.017453292519943295)
            gl.fn('glUniform1f',None,I,F)(self.uniforms['exposure'],s['exposure'])
            gl.fn('glUniform4f',None,I,F,F,F,F)(self.uniforms['viewport'],*viewport)
            gl.fn('glUniform3f',None,I,F,F,F)(self.uniforms['cameraPosition'],*inverse(view)[12:15])
            raw=(F*16)(*inverse(multiply(proj,view)))
            gl.fn('glUniformMatrix4fv',None,I,I,C.c_ubyte,P)(self.uniforms['inverseViewProjection'],1,0,raw)
            gl.fn('glBegin',None,U)(7)
            for x,y in ((-1,-1),(1,-1),(1,1),(-1,1)):gl.fn('glVertex2f',None,F,F)(x,y)
            gl.fn('glEnd',None)()
        finally:gl.fn('glUseProgram',None,U)(previous.value);gl.fn('glPopAttrib',None)()
    def close(self):
        if self.program:self.gl.fn('glDeleteProgram',None,U)(self.program);self.program=0


def sun_settings(value):
    if not value:return None
    d={'texture':value} if isinstance(value,str) else dict(value)
    if not d.get('texture'):raise ValueError('Sun texture is required')
    d['size']=finite(d.get('size',8));d['brightness']=finite(d.get('brightness',1));d['blackAsAlpha']=bool(d.get('blackAsAlpha',True))
    if not .1<=d['size']<=90 or not 0<=d['brightness']<=16:raise ValueError('Sun size 0.1..90 degrees; brightness 0..16')
    return d
