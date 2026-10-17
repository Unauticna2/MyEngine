from engine_runtime import Behaviour

class Script(Behaviour):
    def update(self, dt):
        keys = self.world.input
        speed = 3.0 * dt
        # I/K: forward/back; J/L: left/right; U/O: down/up.
        self.entity.move(keys.axis('J', 'L') * speed,
                         keys.axis('U', 'O') * speed,
                         keys.axis('I', 'K') * speed)
        if keys.pressed('T'):
            self.entity.texture = None if self.entity.texture else 'textures/checker.png'
