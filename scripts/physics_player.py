"""Upright box player: WASD, Shift, Space; native mouse look remains enabled."""
import math
from engine_runtime import Behaviour

class Script(Behaviour):
    def start(self):
        if self.world.camera.rigidbody is None:
            self.world.camera.add_rigidbody(mass=80, friction=0, linear_damping=0)
        self.jump_requested = False

    def update(self, dt):
        if self.world.input.pressed('SPACE'):
            self.jump_requested = True

    def fixed_update(self, dt):
        camera = self.world.camera
        rb = camera.rigidbody
        keys = self.world.input
        x, z = keys.axis('A', 'D'), keys.axis('S', 'W')
        length = math.hypot(x, z)
        if length > 1: x, z = x/length, z/length
        speed = 8.0 if keys.down('SHIFT') else 4.0
        yaw = math.radians(camera.yaw)
        rb.velocity.x = (x*math.cos(yaw)+z*math.sin(yaw))*speed
        rb.velocity.z = (x*math.sin(yaw)-z*math.cos(yaw))*speed
        if self.jump_requested and rb.grounded:
            rb.velocity.y = 5.5
        self.jump_requested = False
        if camera.position.y < -60:
            rb.teleport((0, 3, 8))
