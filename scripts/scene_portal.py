from engine_runtime import Behaviour

class Script(Behaviour):
    def on_trigger_enter(self, other):
        if other.is_player:
            target = 'map-physics.json' if self.world.scene_path.name == 'map-physics2.json' else 'map-physics2.json'
            self.world.load_scene(target)
