"""Select this in Player physics → script. self.entity is the camera."""
import math
from engine_runtime import Behaviour

class Script(Behaviour):
    def fixed_update(self, dt):
        camera = self.entity
        keys = self.world.input
        yaw = math.radians(camera.yaw)
        right, forward = keys.axis('A', 'D'), keys.axis('S', 'W')
        speed = 4.0 / max(1.0, math.hypot(right, forward))
        body = camera.rigidbody
        body.velocity = (speed * (right * math.cos(yaw) + forward * math.sin(yaw)),
                         body.velocity.y,
                         speed * (right * math.sin(yaw) - forward * math.cos(yaw)))
