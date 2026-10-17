from engine_runtime import Behaviour
class Script(Behaviour):
    def start(self):
        self.entity.color=(.8,.3,.1)
        self.entity.add_box_collider()
        self.entity.add_rigidbody(mass=1)
