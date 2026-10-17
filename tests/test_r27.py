"""R27 real headless rendering, runtime PNG roundtrip and component/Blueprint checks."""
import ctypes as C
import json
import math
from pathlib import Path
import tempfile
import sys
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
from engine_lighting import light_settings,light_color,collect,contribution
from engine_materials import material_settings
from engine_scene import SceneDocument
from engine_blueprints import generated_source
from engine_ui_blueprints import click_graph
from PNGJSONUnitylity import PNGJSONUnitylity

ROOT=Path(__file__).resolve().parents[1]
QUAD='v -1 -1 0\nv 1 -1 0\nv 1 1 0\nv -1 1 0\nvn 0 0 1\nf 1//1 2//1 3//1 4//1\n'


class ComponentTests(unittest.TestCase):
    def test_signed_hdr_rgb_hsv_temperature(self):
        self.assertEqual(light_color(light_settings({'color':[-2,.3,4],'intensity':-2})),(4,-.6,-8))
        self.assertEqual(light_color(light_settings({'colorMode':'hsv','hsv':[120,1,2]})),(0,2,0))
        warm=light_color(light_settings({'colorMode':'temperature','temperature':2000}))
        self.assertGreater(warm[0],warm[2])
    def test_range_spot_and_signed_attenuation(self):
        row={'type':'spot','position':(0,0,2),'direction':(0,0,-1),'color':(-1,2,0),'range':4,'inner':.95,'outer':.8}
        self.assertEqual(contribution(row,(0,0,0),(0,0,1)),(-.25,.5,0))
        self.assertEqual(contribution(row,(10,0,0),(0,0,1)),(0,0,0))
        self.assertEqual(contribution(row,(0,0,3),(0,0,-1)),(0,0,0))
    def test_legacy_light_disabled_when_a_disabled_component_exists(self):
        world=NS(camera=NS(position=(0,0,0)),light_rotation=(0,0,0),entities=[])
        self.assertTrue(collect(world)['legacy'])
        world.entities=[NS(destroyed=False,active=True,light=light_settings({'enabled':False}))]
        self.assertFalse(collect(world)['legacy'])
    def test_settings_validation_and_scene_prefab_columns(self):
        for value in [{'type':'bad'},{'range':0},{'innerAngle':70,'outerAngle':30},{'color':[float('nan'),0,0]}]:
            with self.assertRaises(ValueError):light_settings(value)
        for value in [{'opacity':-1},{'mode':'bad'},{'voxelDensity':-2}]:
            with self.assertRaises(ValueError):material_settings(value)
        doc=SceneDocument({'model':[None],'lights':[{'type':'spot','intensity':-1}]})
        doc.duplicate(0);self.assertEqual(len(doc.data['lights']),2)
        doc.remove(0);self.assertEqual(doc.data['lights'][0]['intensity'],-1)
    def test_blueprint_actions_and_ui_templates(self):
        for kind in ('SavePNG','LoadPNG'):
            source,_=generated_source(click_graph('1','button',kind))
            compile(source,'graph.py','exec')
            self.assertIn('save_game_png' if kind=='SavePNG' else 'load_game_png',source)
        data={'format':1,'nodes':[{'id':'1','type':'Update'},{'id':'2','type':'PNGIs','params':{'key':'slot','state':'saved'}},
              {'id':'3','type':'Branch'},{'id':'4','type':'LightIntensity','params':{'value':-2}}],
              'links':[['1','next','3','in'],['2','value','3','condition'],['3','true','4','in']]}
        source,_=generated_source(data);self.assertIn('saves.state',source);self.assertIn('= -2',source)


@unittest.skipUnless(sys.platform=='linux','Headless EGL/LinuxCore checks run on Linux')
class RenderAndSaveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from egl_context import EGLContext
        cls.egl=EGLContext(128,128)
    @classmethod
    def tearDownClass(cls):cls.egl.close()
    def setUp(self):
        from engine_linux import LinuxCore
        from engine_runtime import World
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        (self.root/'quad.obj').write_text(QUAD)
        doc=SceneDocument.empty();doc.data.update(shadows={'enabled':False},reflections={'enabled':False},lighting={'legacy':'off','ambient':[1,1,1]})
        doc.save(self.root/'scene.json')
        self.core=LinuxCore(ROOT,window=False);self.core.size=(128,128)
        self.world=World(self.core,self.root);self.world.load('scene.json')
        self.world.camera.position=(0,0,3);self.world.camera.pitch=0;self.world.camera.yaw=0
    def tearDown(self):
        self.world.shutdown();self.core.close();self.temp.cleanup()
    def draw(self):
        self.core.begin_frame();self.world.draw()
        raw=(C.c_ubyte*4)()
        from engine_gl import I,U,P
        self.core.gl.fn('glReadPixels',None,I,I,I,I,U,U,P)(64,64,1,1,0x1908,0x1401,raw)
        error=self.core.gl.fn('glGetError',U)();self.assertEqual(error,0)
        self.assertFalse(self.world.render_failed)
        return tuple(raw[:3])
    def test_point_spot_and_negative_lighting_pixels(self):
        w=self.world;w.lighting={'legacy':'off','ambient':[.1,.1,.1]}
        w.instantiate('quad.obj')
        light=w.instantiate(position=(0,0,2),rotation=(0,180,0),light={'type':'point','color':[1,0,0],'range':4})
        positive=self.draw();self.assertGreater(positive[0],positive[1]+40)
        light.light['intensity']=-1;negative=self.draw();self.assertLess(negative[0],positive[0]-40)
        light.add_light('spot',range=4,color=[0,1,0]);spot=self.draw();self.assertGreater(spot[1],spot[0]+40)
        light.rotation=(0,0,0);away=self.draw();self.assertLess(away[1],spot[1]-40)
    def test_transparent_polygon_blends_over_opaque_polygon(self):
        w=self.world;w.instantiate('quad.obj',position=(0,0,-1),scale=(3,3,3),color=(0,0,1))
        w.instantiate('quad.obj',color=(1,0,0),material={'mode':'transparent','opacity':.5})
        red,green,blue=self.draw();self.assertTrue(115<=red<=140,(red,green,blue));self.assertTrue(115<=blue<=140)
    def test_voxel_volume_blends_and_stops_at_opaque_geometry(self):
        from engine_voxels import VoxelGrid,VoxelRenderer
        w=self.world;grid=VoxelGrid((1,1,1),1);grid.set(0,0,0,(255,0,0,255))
        w.instantiate(voxels=VoxelRenderer(grid),material={'mode':'transparent','opacity':.5})
        back=w.instantiate('quad.obj',position=(0,0,-1),scale=(3,3,3),color=(0,0,1))
        whole=self.draw();self.assertTrue(85<=whole[0]<=115,whole);self.assertGreater(whole[2],130)
        back.position=(0,0,0);back.sync();half=self.draw();self.assertLess(half[0],whole[0]-25)
        back.position=(0,0,1);back.sync();hidden=self.draw();self.assertLess(hidden[0],3);self.assertGreater(hidden[2],250)
    def test_camera_inside_volume_has_stable_pixels(self):
        from engine_voxels import VoxelGrid,VoxelRenderer
        g=VoxelGrid((2,2,2),1)
        for z in range(2):
            for y in range(2):
                for x in range(2):g.set(x,y,z,(50,200,255,120))
        self.world.instantiate(voxels=VoxelRenderer(g),material={'mode':'transparent','opacity':.5})
        self.world.camera.position=(.2,.2,.2)
        first=self.draw();self.assertEqual(first,self.draw());self.assertGreater(first[2],30)
    def test_directional_shadow_reflection_capture_and_liquid(self):
        from engine_materials import reflection_settings
        from engine_render import settings
        w=self.world;w.shadows=settings({'enabled':True,'size':512})
        w.reflections=reflection_settings({'enabled':True,'size':64,'facesPerFrame':6})
        w.instantiate('quad.obj',material={'metallic':.8})
        w.instantiate(rotation=(0,180,0),light={'type':'directional'})
        w.instantiate('quad.obj',position=(1,0,1),material={'mode':'transparent','opacity':.4})
        water=w.instantiate(position=(0,-1,0),liquid={'nx':4,'nz':4},material={'mode':'transparent','opacity':.5})
        self.draw()
        self.assertTrue(w.scene_renderer.ready)
        self.assertTrue(w.scene_renderer.probe.ready)
        self.assertFalse(w.scene_renderer.probe.failed)
        self.assertIsNotNone(water.liquid)
    def test_png_restores_player_spawned_objects_physics_and_voxels(self):
        from engine_runtime import finish_frame
        from engine_voxels import VoxelGrid,VoxelRenderer
        w=self.world;w.camera.position=(2,4,6);w.camera.yaw=25;w.camera.w=.7
        w.camera.configure_physics('walk');w.camera.rigidbody.velocity=(1,2,3)
        thing=w.instantiate('quad.obj',name='Spawned',position=(1,2,3),rotation=(10,20,30),scale=(2,2,2),
                            collider={'type':'box'},rigidbody={'velocity':[4,5,6]},material={'mode':'transparent','opacity':.4},
                            light={'type':'point','color':[-1,0,3]})
        g=VoxelGrid((2,1,1),.2);g.set(1,0,0,(10,20,30,100));w.instantiate(name='Edited voxels',voxels=VoxelRenderer(g))
        self.assertTrue(w.save_game_png('saves/slot.png'))
        self.core.begin_frame();w._finish_screenshots()
        w.saves.records['save']['future'].result(timeout=5);w.saves.poll()
        self.assertEqual(w.saves.state(),'saved')
        payload=PNGJSONUnitylity.FromPngJson(self.root/'saves/slot.png');self.assertEqual(payload['kind'],'MyEngine.World')
        w.destroy(thing);w._flush_destroy();w.instantiate(name='Created after save');w.camera.position=(99,99,99)
        self.assertTrue(w.load_game_png('saves/slot.png'));w.saves.pending[1].result(timeout=5)
        restored=finish_frame(w);self.assertIsNot(restored,w);self.world=restored
        self.assertEqual(restored.saves.state(),'loaded');self.assertEqual(tuple(restored.camera.position),(2,4,6))
        self.assertAlmostEqual(restored.camera.w,.7,places=5);self.assertEqual(restored.camera.yaw,25)
        self.assertEqual(tuple(restored.camera.rigidbody.velocity),(1,2,3))
        e=restored.find('Spawned');self.assertEqual(tuple(e.position),(1,2,3));self.assertEqual(tuple(e.rigidbody.velocity),(4,5,6))
        self.assertIsNone(restored.find('Created after save'));self.assertEqual(e.light['color'],[-1,0,3])
        self.assertEqual(e.material['mode'],'transparent');self.assertEqual(restored.find('Edited voxels').voxels.grid.get(1,0,0),(10,20,30,100))
    def test_corrupt_png_leaves_running_world_intact(self):
        from engine_runtime import finish_frame
        (self.root/'bad.png').write_bytes(b'not a PNG');w=self.world;w.instantiate(name='Keep me')
        self.assertTrue(w.load_game_png('bad.png'))
        try:w.saves.pending[1].result(timeout=5)
        except ValueError:pass
        self.assertIs(finish_frame(w),w);self.assertIsNotNone(w.find('Keep me'));self.assertEqual(w.saves.state(),'error')
    def test_restore_hooks_resume_scripts_without_replaying_start(self):
        from engine_runtime import finish_frame
        (self.root/'resume.py').write_text('''from engine_runtime import Behaviour
class Script(Behaviour):
    def __init__(self):
        self.counter=0
    def start(self):
        self.world.instantiate(name="Start spawned once");self.counter=42
    def save_state(self):return {"counter":self.counter}
    def load_state(self,data):self.counter=data["counter"]
    def on_restore(self):self.counter+=1
''')
        w=self.world;e=w.instantiate(name='Script owner',scripts=['resume.py']);w._flush_starts()
        self.assertEqual(e.get_script().counter,42);self.assertTrue(w.save_game_png('resume.png'))
        self.core.begin_frame();w._finish_screenshots();w.saves.records['save']['future'].result(timeout=5)
        self.assertTrue(w.load_game_png('resume.png'));w.saves.pending[1].result(timeout=5)
        self.world=finish_frame(w);self.assertIsNot(self.world,w)
        self.assertEqual(self.world.find('Script owner').get_script().counter,43)
        self.assertEqual(sum(e.name=='Start spawned once' for e in self.world.entities),1)


if __name__=='__main__':unittest.main()
