from engine_runtime import Behaviour

# region MYENGINE_BLUEPRINT
_bp_ui_path = None
_bp_ui_click_targets = ()
def _bp_start(self, dt=0.0):
    pass

def _bp_update(self, dt=0.0):
    pass

def _bp_fixed_update(self, dt=0.0):
    pass

def _bp_ui_click(self, slide, element, dt=0.0):
    pass

def _bp_on_collision_enter(self, collision):
    other = collision.other
    dt = self.world.physics.fixed_delta_time
    # Print node 'action0'
    self.world.log('OnCollisionEnter')

def _bp_on_collision_stay(self, collision):
    other = collision.other
    dt = self.world.physics.fixed_delta_time
    # Print node 'action1'
    self.world.log('OnCollisionStay')

def _bp_on_collision_exit(self, collision):
    other = collision.other
    dt = self.world.physics.fixed_delta_time
    # Print node 'action2'
    self.world.log('OnCollisionExit')

def _bp_on_trigger_enter(self, other):
    dt = self.world.physics.fixed_delta_time
    # Print node 'action3'
    self.world.log('OnTriggerEnter')

def _bp_on_trigger_stay(self, other):
    dt = self.world.physics.fixed_delta_time
    # Print node 'action4'
    self.world.log('OnTriggerStay')

def _bp_on_trigger_exit(self, other):
    dt = self.world.physics.fixed_delta_time
    # Print node 'action5'
    self.world.log('OnTriggerExit')

_bp_physics_callbacks = {'on_collision_enter': _bp_on_collision_enter, 'on_collision_stay': _bp_on_collision_stay, 'on_collision_exit': _bp_on_collision_exit, 'on_trigger_enter': _bp_on_trigger_enter, 'on_trigger_stay': _bp_on_trigger_stay, 'on_trigger_exit': _bp_on_trigger_exit}
# endregion MYENGINE_BLUEPRINT

class Script(Behaviour):
    def start(self):
        _bp_start(self)

    def update(self, dt):
        _bp_update(self, dt)

    def fixed_update(self, dt):
        _bp_fixed_update(self, dt)

# Write your extra Python outside the generated region.
