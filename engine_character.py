"""Camera character: switchable native-physics box, free flight or Python controller."""
import math
from engine_assets import finite
from engine_physics import Collider as BoxCollider

class CharacterController:
    def __init__(self,camera,mode='walk',size=(.5,1.6,.5),center=(0,-.6,0),mass=75,speed=3.5,sprint=7,jump=5,script=None):
        if mode not in ('fly','walk','script'):raise ValueError('Character mode: fly, walk or script')
        values=[finite(x) for x in (mass,speed,sprint,jump)]
        if values[0]<=0 or min(values[1:])<0:raise ValueError('Mass must be positive; speeds nonnegative')
        collider=BoxCollider.from_json({'type':'box','size':list(size),'center':list(center)})
        if mode=='script' and not script:raise ValueError('Select a character Python script')
        self.camera=camera;self.mode=mode;self.speed=values[1];self.sprint=values[2];self.jump_speed=values[3];self.jump=False
        # Resolve the script before replacing a live controller.
        if mode=='script':
            from engine_runtime import ScriptBinding
            from engine_assets import asset_path
            binding=ScriptBinding(camera,asset_path(camera.world.root,script))
            if not binding.reload(defer_start=True):raise ValueError('Character script failed to load')
        else:binding=None
        import sys
        for old in camera.scripts:old.call('on_destroy',force=True);sys.modules.pop(old.module_name,None)
        camera.scripts=[];camera.world._starts=[b for b in camera.world._starts if b.entity is not camera]
        camera.world.physics.forget(camera);camera.rigidbody=None;camera.collider=collider
        camera.control_enabled=mode=='fly'
        if mode!='fly':camera.add_rigidbody(mass=values[0],freeze_rotation=True,linear_damping=0)
        if binding:camera.scripts.append(binding);camera.world._starts.append(binding)
    def update(self):
        if self.mode=='walk' and self.camera.world.input.pressed('SPACE'):self.jump=True
    def fixed_update(self,dt):
        if self.mode!='walk':return
        c=self.camera;keys=c.world.input;yaw=math.radians(c.yaw)
        right=keys.axis('A','D');forward=keys.axis('S','W');n=max(1,math.hypot(right,forward))
        speed=(self.sprint if keys.down('SHIFT') else self.speed)/n;rb=c.rigidbody
        if rb is None:return
        y=rb.velocity.y
        if self.jump and rb.grounded:y=self.jump_speed
        self.jump=False
        rb.velocity=(speed*(forward*math.sin(yaw)+right*math.cos(yaw)),y,speed*(right*math.sin(yaw)-forward*math.cos(yaw)))
