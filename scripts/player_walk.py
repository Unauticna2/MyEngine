"""Attach to an empty scene object. Physics camera in Play; editor camera remains free."""
import math
from engine_runtime import Behaviour

class Script(Behaviour):
    def start(self):
        self.camera=self.world.camera;self.jump=False
        if self.camera.rigidbody is None:self.camera.add_rigidbody(mass=75,freeze_rotation=True,linear_damping=0)
        self.camera.control_enabled=False
    def update(self,dt):
        if self.world.input.pressed('SPACE'):self.jump=True
    def fixed_update(self,dt):
        keys=self.world.input;yaw=math.radians(self.camera.yaw)
        right=keys.axis('A','D');forward=keys.axis('S','W');n=max(1,math.hypot(right,forward))
        speed=(7 if keys.down('SHIFT') else 3.5)/n
        rb=self.camera.rigidbody;vertical=rb.velocity.y
        if self.jump and rb.grounded:vertical=5
        self.jump=False
        rb.velocity=(speed*(forward*math.sin(yaw)+right*math.cos(yaw)),vertical,speed*(right*math.sin(yaw)-forward*math.cos(yaw)))
