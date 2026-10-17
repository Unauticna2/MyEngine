"""Press P in Play to spawn a two-object prefab; press O to destroy its instances."""
from engine_runtime import Behaviour

class Script(Behaviour):
    def start(self):
        self.stats = self.world.resources.scriptable('assets/data/Mover.scriptable.json', clone=True)
        self.spawned = []
        self.world.log('2.4 demo: P = spawn prefab, O = remove spawned objects; F1/F2/F3/F4/F6/F7 = light.')

    def update(self, dt):
        if self.world.input.pressed('P'):
            self.spawned.extend(self.world.instantiate_prefab(
                'assets/prefabs/Pair.prefab.json', position=(0, 2, -3), prefix='Pair'))
        if self.world.input.pressed('O'):
            for entity in self.spawned:
                entity.destroy()
            self.spawned.clear()
