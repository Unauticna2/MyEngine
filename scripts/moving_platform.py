import math
from engine_runtime import Behaviour

class Script(Behaviour):
    def start(self):
        self.origin = tuple(self.entity.position)

    def fixed_update(self, dt):
        x, y, z = self.origin
        self.entity.rigidbody.move_position((x, y + math.sin(self.world.fixed_time)*.6, z))
