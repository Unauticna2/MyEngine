from engine_runtime import Behaviour

# region MYENGINE_BLUEPRINT
def _bp_start(self, dt=0.0):
    pass

def _bp_update(self, dt=0.0):
    # Rotate node '5'
    self.entity.rotate(0, ((float(self.world.resources.scriptable('assets/data/Mover.scriptable.json')['speed'])) * dt), 0)

def _bp_fixed_update(self, dt=0.0):
    pass

# endregion MYENGINE_BLUEPRINT

class Script(Behaviour):
    def start(self):
        _bp_start(self)

    def update(self, dt):
        _bp_update(self, dt)

    def fixed_update(self, dt):
        _bp_fixed_update(self, dt)

# Write your extra Python outside the generated region.
