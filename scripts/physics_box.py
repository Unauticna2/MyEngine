from engine_runtime import Behaviour

class Script(Behaviour):
    def start(self):
        self.age = 0.0

    def update(self, dt):
        self.age += dt
        if self.age > 30 or self.entity.position.y < -100:
            self.entity.destroy()

    def on_collision_enter(self, collision):
        # collision.other, point, normal, penetration, impulse are available.
        if collision.normal[1] > .5:
            self.entity.color = (.2, .8, 1.0)
