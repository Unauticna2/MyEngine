from engine_runtime import Behaviour

class Script(Behaviour):
    def start(self):
        self.target = self.world.find('keyboard_cube')
        self.old_color = tuple(self.target.color) if self.target else (1, 1, 1)

    def on_trigger_enter(self, other):
        if other.is_player:
            self.world.log('PLAYER ENTERED trigger:', self.entity.name)
            if self.target:
                self.target.color = (1.0, 0.9, 0.15)

    def on_trigger_stay(self, other):
        if other.is_player and self.target:
            self.target.rotation.y += 80.0 * self.world.delta_time

    def on_trigger_exit(self, other):
        if other.is_player:
            self.world.log('PLAYER LEFT trigger:', self.entity.name)
            if self.target:
                self.target.color = self.old_color
