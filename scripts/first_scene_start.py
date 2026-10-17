from engine_runtime import Behaviour

# region MYENGINE_BLUEPRINT
_bp_ui_path = None
_bp_ui_click_targets = ()
def _bp_start(self, dt=0.0):
    # Print node 'loaded'
    self.world.log('Scene object started')

def _bp_first_scene_start(self, dt=0.0):
    # Print node 'intro'
    self.world.log('First visit to this scene during this game session')

def _bp_update(self, dt=0.0):
    pass

def _bp_fixed_update(self, dt=0.0):
    pass

def _bp_ui_click(self, slide, element, dt=0.0):
    pass

_bp_physics_callbacks = {}
# endregion MYENGINE_BLUEPRINT

class Script(Behaviour):
    def start(self):
        _bp_start(self)

    def update(self, dt):
        _bp_update(self, dt)

    def fixed_update(self, dt):
        _bp_fixed_update(self, dt)

# Write your extra Python outside the generated region.
