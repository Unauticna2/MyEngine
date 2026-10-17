from types import SimpleNamespace as NS
import unittest
from engine_reflections import capture_selection,face_matrices,FACES
from engine_materials import reflection_settings
from tests.test_materials_r20 import entity
class ReflectionTests(unittest.TestCase):
    def test_capture_selects_actual_geometry_and_excludes_self_hidden_and_far(self):
        anchor=entity();anchor._native.mesh=1;anchor.material={'metallic':1,'reflectionStrength':1}
        items=[entity((x,0,0)) for x in (5,12,500)];hidden=entity();hidden.visible=False
        for e in items+[hidden]:e._native.mesh=2;e.material={}
        world=NS(entities=[anchor,*items,hidden],camera=NS(position=(0,0,10)))
        a,center,draws=capture_selection(world,reflection_settings({'maxDraws':1,'distance':40}))
        self.assertIs(a,anchor);self.assertEqual(center,(0,0,0));self.assertEqual(draws,[items[0]])
    def test_each_cubemap_axis_maps_to_forward(self):
        center=(3,4,5)
        for face,(direction,up) in enumerate(FACES):
            view,projection=face_matrices(center,face,40)
            point=[center[k]+direction[k] for k in range(3)]+[1]
            transformed=[sum(view[j*4+i]*point[j] for j in range(4)) for i in range(4)]
            self.assertEqual(transformed,[0,0,-1,1]);self.assertEqual(projection[0],projection[5])
    def test_budget_validation(self):
        for value in ({'size':100},{'size':True},{'facesPerFrame':7},{'maxDraws':0},{'updateInterval':-1}):
            with self.assertRaises(ValueError):reflection_settings(value)
