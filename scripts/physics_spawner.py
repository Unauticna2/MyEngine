"""1: throw a scripted box, 2: remove it, 3: reload, 4: next demo, 6: physics demo."""
import math
from engine_runtime import Behaviour

class Script(Behaviour):
    def start(self):
        self.last_box = None
        self.world.log('Physics: 1 spawn, 2 destroy last, 3 reload, 4 next demo, 6 physics demo')

    def update(self, dt):
        keys = self.world.input
        if keys.pressed('1'):
            camera = self.world.camera
            yaw, pitch = math.radians(camera.yaw), math.radians(camera.pitch)
            direction = (math.sin(yaw)*math.cos(pitch), -math.sin(pitch), -math.cos(yaw)*math.cos(pitch))
            position = tuple(p+d*2.0 for p,d in zip(camera.position, direction))
            self.last_box = self.world.instantiate(
                'assets/Cube.obj', position=position,
                rotation=(10, 20, 15), scale=(.4, .4, .4), color=(1, .55, .12),
                texture='textures/checker.png', scripts=['scripts/physics_box.py'],
                collider={'type': 'box'},
                rigidbody={'mass': 1, 'friction': .6, 'restitution': .25,
                           'angular_velocity': (1, 2, .5)})
            self.last_box.rigidbody.add_force(tuple(d*8 for d in direction), mode='impulse')
        if keys.pressed('2') and self.last_box and not self.last_box.destroyed:
            self.world.destroy(self.last_box)
        if keys.pressed('3'):
            self.world.reload_scene()
        if keys.pressed('4'):
            next_scene = 'map-physics.json' if self.world.scene_path.name == 'map-physics2.json' else 'map-physics2.json'
            self.world.load_scene(next_scene)
        if keys.pressed('6'):
            self.world.load_scene('map-physics.json')
