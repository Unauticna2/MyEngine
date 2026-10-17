from engine_runtime import Behaviour

class Script(Behaviour):
    def update(self, dt):
        self.entity.rotate(y=20*dt)

    def start(self):
        # Voxel coordinates are local integer grid coordinates. Alpha 0 removes a cell.
        if self.entity.voxels:
            self.entity.set_voxel(20,20,39,(255,180,40,255))
