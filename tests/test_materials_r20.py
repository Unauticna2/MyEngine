import math
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock
from engine_materials import material_settings,reflection_settings,reflection_proxies,world_bounds,ray_box
from engine_scene import SceneDocument
from engine_editor_link import RuntimeEditor

def entity(position=(0,0,0),rotation=(0,0,0),scale=(1,1,1)):
    return NS(voxels=None,layers=[NS(minimum=(-1,-2,-3),maximum=(1,2,3))],layer=0,
              position=position,rotation=rotation,scale=scale,color=(1,.2,.1),destroyed=False,active=True,visible=True,_native=NS(visible=True))

class MaterialsTests(unittest.TestCase):
    def test_scene_roundtrip_duplicate_undo_and_old_default(self):
        doc=SceneDocument({'model':[None]});self.assertEqual(material_settings(doc.data['materials'][0])['metallic'],0)
        doc.set_object(0,{'materials':{'metallic':1,'roughness':.12}})
        i=doc.duplicate(0);self.assertEqual(doc.data['materials'][i]['metallic'],1)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'scene.json';doc.save(path);self.assertEqual(SceneDocument.load(path).data,doc.data)
        doc.undo();self.assertEqual(len(doc.data['materials']),1)
        with self.assertRaises(ValueError):doc.set_object(0,{'materials':{'metallic':2}})
        self.assertEqual(doc.data['materials'][0]['metallic'],1)
    def test_invalid_values_rejected_before_live_object_creation(self):
        for value in ({'metallic':True},{'roughness':float('nan')},{'reflectionStrength':-1},[],'x'):
            with self.assertRaises(ValueError):material_settings(value)
        world=NS(find=lambda name:NS(is_player=False),instantiate=Mock())
        with self.assertRaises(ValueError):RuntimeEditor.replace_object(world,'Cube',{'names':'Cube','materials':{'roughness':2}})
        world.instantiate.assert_not_called()
        for value in ({'maxObjects':9},{'maxObjects':True},{'distance':0},{'enabled':'yes'}):
            with self.assertRaises(ValueError):reflection_settings(value)
    def test_aabb_contains_transformed_corners_with_negative_scale(self):
        from engine_collision import rotation_axes
        e=entity((10,3,-4),(20,45,10),(-2,.5,3));e.layers[0].minimum=(0,1,2)
        lo,hi=world_bounds(e);axes=rotation_axes(e.rotation)
        for x in (0,1):
            for y in (1,2):
                for z in (2,3):
                    corner=(x,y,z)
                    world=tuple(e.position[k]+sum(axes[i][k]*e.scale[i]*corner[i] for i in range(3)) for k in range(3))
                    for k in range(3):self.assertLessEqual(lo[k]-1e-9,world[k]);self.assertLessEqual(world[k],hi[k]+1e-9)
    def test_budget_hidden_and_far_objects(self):
        items=[entity((i*10,0,0)) for i in range(20)];items[0].visible=False
        settings=reflection_settings({'distance':500});proxies=reflection_proxies(items,(0,0,0),settings)
        self.assertEqual(len(proxies),8);self.assertIs(proxies[0][0],items[1])
        self.assertEqual(len(reflection_proxies(items,(0,0,0),reflection_settings({'distance':15}))),1)
        self.assertEqual(reflection_proxies(items,(0,0,0),reflection_settings({'enabled':False})),[])
    def test_parallel_outside_inside_and_backwards_rays(self):
        lo=(-1,-1,-1);hi=(1,1,1)
        self.assertEqual(ray_box((0,0,5),(0,0,-1),lo,hi),4)
        self.assertIsNone(ray_box((2,0,5),(0,0,-1),lo,hi))
        self.assertIsNone(ray_box((0,0,5),(0,0,1),lo,hi))
        self.assertEqual(ray_box((0,0,0),(1,0,0),lo,hi),1)

if __name__=='__main__':unittest.main()
