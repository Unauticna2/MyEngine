from engine_runtime import Behaviour

# region MYENGINE_BLUEPRINT
_bp_ui_path = None
_bp_ui_click_targets = ()
def _bp_start(self, dt=0.0):
    pass

def _bp_update(self, dt=0.0):
    # Branch node 'savebranch'
    if self.world.input.pressed('F8'):
        # SavePNG node 'save'
        self.world.save_game_png('saves/demo-r27.png', 'demo')
    else:
        # Branch node 'loadbranch'
        if self.world.input.pressed('F9'):
            # LoadPNG node 'load'
            self.world.load_game_png('saves/demo-r27.png', 'demo')
        else:
            # Branch node 'spawnbranch'
            if self.world.input.pressed('N'):
                # Spawn node 'spawn'
                self.world.instantiate('assets/Cube.obj', position=(0, 4, 0), scripts=['scripts/r27_spawned.py'])
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
