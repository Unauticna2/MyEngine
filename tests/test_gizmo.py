import unittest
from types import SimpleNamespace as NS
from engine_gizmo import Gizmo,snapshot,project,segment_distance
from engine_gl import model_matrix,inverse
from engine_runtime import Vec3

class Entity:
    def __init__(self):
        self.position=(0,0,0);self.rotation=(0,0,0);self.scale=(1,1,1)
        self.rotation4=Vec3();self.w=0;self.scale_w=1;self.is_4d=True;self.layer_spacing=.1
        self.name='Test';self.destroyed=False;self.world=NS(core=NS(camera_control=NS(value=1)))
    @staticmethod
    def vector(v):return Vec3(*(v[k] for k in 'xyz')) if isinstance(v,dict) else Vec3(*v)
    @property
    def position(self):return self._position
    @position.setter
    def position(self,v):self._position=self.vector(v)
    @property
    def rotation(self):return self._rotation
    @rotation.setter
    def rotation(self,v):self._rotation=self.vector(v)
    @property
    def scale(self):return self._scale
    @scale.setter
    def scale(self,v):self._scale=self.vector(v)

class GizmoTests(unittest.TestCase):
    def setUp(self):
        self.messages=[];self.e=Entity();self.g=Gizmo(NS(channel=NS(send=self.messages.append)),None,mouse=object())
        self.identity=model_matrix((0,0,0),(0,0,0),(1,1,1))
    def begin(self,mode,axis=0):
        self.g.mode=mode
        h={'axis':axis,'points':[(0,0),(100,0)],'length':2,'center':(100,100),'normal':(0,0,1)}
        self.g.begin(self.e,h,(0,0),self.identity,200,200)
    def test_move_xyz_w_and_commit(self):
        for axis in range(4):
            self.begin('move',axis);self.g.motion((50,0));self.g.finish()
        self.assertEqual(tuple(self.e.position),(1,1,1));self.assertEqual(self.e.w,1)
        self.assertEqual(self.e.world.core.camera_control.value,1)
        self.assertEqual(sum(m['type']=='gizmo_commit' for m in self.messages),4)
        self.assertTrue(self.messages[-1]['changed'])
    def test_scale_cancel_and_restore(self):
        before=snapshot(self.e);self.begin('scale',3);self.g.motion((100,0));self.assertEqual(self.e.scale_w,2)
        self.assertEqual(self.e.world.core.camera_control.value,0)
        self.g.cancel();self.assertEqual(snapshot(self.e),before);self.assertEqual(self.e.world.core.camera_control.value,1)
        self.assertEqual(self.messages[-1]['type'],'gizmo_cancel')
    def test_xyz_rotation_ray_plane(self):
        self.g.mode='rotate';h={'axis':2,'normal':(0,0,1),'center':(100,100)}
        self.g.begin(self.e,h,(150,100),self.identity,200,200);self.g.motion((100,50));self.g.finish()
        self.assertAlmostEqual(self.e.rotation.z,90,places=5)
    def test_four_d_rotation_and_snap(self):
        self.g.mode='rotate4';h={'axis':1,'center':(100,100)}
        self.g.begin(self.e,h,(150,100),self.identity,200,200);self.g.motion((100,150));self.g.finish()
        self.assertAlmostEqual(self.e.rotation4.y,90,places=5)
        self.begin('move');self.g.motion((13,0),snap=True);self.g.finish();self.assertAlmostEqual(self.e.position.x,.3,places=5)
    def test_projection_and_hit_distance(self):
        self.assertEqual(project(self.identity,(0,0,0),200,100),(100,50))
        self.assertEqual(segment_distance((50,5),(0,0),(100,0)),5)
        self.assertEqual(segment_distance((103,4),(0,0),(100,0)),5)

if __name__=='__main__':unittest.main()
