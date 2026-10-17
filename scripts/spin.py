from engine_runtime import Behaviour

class Script(Behaviour):
    def update(self, dt):
        self.entity.rotation.y = (self.entity.rotation.y + 35.0 * dt) % 360.0
