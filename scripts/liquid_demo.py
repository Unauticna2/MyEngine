"""1 = splash, 2 = add 0.5 cubic units of water. Commands use local pool X/Z."""
from engine_runtime import Behaviour

class Script(Behaviour):
    def start(self):
        self.entity.liquid.splash(-1.5,0,strength=5,radius=1.2)
        self.world.log('Liquid demo: 1 splash, 2 add water. WASD + Space/Ctrl move.')
    def update(self,dt):
        if self.world.input.pressed('1'):
            self.entity.liquid.splash(-1.5,0,strength=6,radius=1.2)
        if self.world.input.pressed('2'):
            self.entity.liquid.add_water(-1.5,0,volume=.5,radius=.7)
