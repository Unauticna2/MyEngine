from engine_runtime import Behaviour

# region MYENGINE_BLUEPRINT
_bp_ui_path = None
_bp_ui_click_targets = ()
def _bp_start(self, dt=0.0):
    pass

def _bp_update(self, dt=0.0):
    # Branch node '3'
    if self.world.transactions.paid_once('donation'):
        # Print node '4'
        self.world.log('Спасибо за поддержку!')
    else:
        pass

def _bp_fixed_update(self, dt=0.0):
    pass

def _bp_ui_click(self, slide, element, dt=0.0):
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
