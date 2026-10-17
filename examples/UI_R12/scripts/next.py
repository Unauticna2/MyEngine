from engine_runtime import Behaviour

# region MYENGINE_BLUEPRINT
_bp_ui_path = 'assets/ui/Demo/interface.ui.json'
_bp_ui_click_targets = (('1', 'next'),)
def _bp_start(self, dt=0.0):
    pass

def _bp_update(self, dt=0.0):
    pass

def _bp_fixed_update(self, dt=0.0):
    pass

def _bp_ui_click(self, slide, element, dt=0.0):
    if (str(slide), str(element)) == ('1', 'next'):
        # UIDialogueNext node '2'
        if self.world.ui is not None:
            self.world.ui.dialogue_next('dialogue', '1')

# endregion MYENGINE_BLUEPRINT

class Script(Behaviour):
    def start(self):
        _bp_start(self)

    def update(self, dt):
        _bp_update(self, dt)

    def fixed_update(self, dt):
        _bp_fixed_update(self, dt)

# Write your extra Python outside the generated region.
