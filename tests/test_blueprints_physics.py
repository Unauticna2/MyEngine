"""Physics -> ScriptBinding -> generated Blueprint execution, including old scripts."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest

from engine_blueprints import PHYSICS_EVENTS, generated_source, save_python
from engine_physics import Collision
from engine_runtime import ScriptBinding, World

ROOT=Path(__file__).resolve().parents[1]


def events_graph(kinds=PHYSICS_EVENTS, **filters):
    nodes=[];links=[]
    for i,kind in enumerate(kinds):
        event=f'e{i}';action=f'a{i}'
        nodes += [{'id':event,'type':kind,'params':dict(filters)},
                  {'id':action,'type':'Print','params':{'text':kind}}]
        links.append([event,'next',action,'in'])
    return {'format':1,'nodes':nodes,'links':links}


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'events.py';self.logs=[]
        self.world=NS(ui=None,scripts_allowed=True,physics=NS(fixed_delta_time=.02),log=self.logs.append)
        self.entity=NS(id=0,name='Zone',world=self.world,script_trusted=True)
        self.binding=ScriptBinding(self.entity,self.path)
        self.addCleanup(lambda:sys.modules.pop(self.binding.module_name,None))
        self.other=NS(name='Cube',is_player=False)

    def bind(self,graph,existing=None,defer=False):
        source,unused=generated_source(graph,existing)
        self.assertEqual(unused,[])
        self.path.write_text(source,encoding='utf-8')
        self.assertTrue(self.binding.reload(defer_start=defer))

    def send(self,kind,other=None):
        other=self.other if other is None else other
        arg=Collision(other,(0,0,0),(0,1,0),.1,0) if 'Collision' in kind else other
        self.binding.call(PHYSICS_EVENTS[kind],arg)

    def test_all_six_callbacks_once_with_existing_behaviour_base_methods(self):
        self.bind(events_graph())
        for kind in PHYSICS_EVENTS:self.send(kind)
        self.assertEqual(self.logs,list(PHYSICS_EVENTS))

    def test_filters_use_other_object_and_support_several_event_nodes(self):
        graph=events_graph(['OnTriggerEnter']*3)
        graph['nodes'][0]['params']={'otherName':'Cube'}
        graph['nodes'][2]['params']={'playerOnly':True}
        graph['nodes'][4]['params']={'otherName':'player','playerOnly':True}
        for i,n in enumerate(graph['nodes'][1::2]):n['params']['text']=str(i)
        self.bind(graph)
        self.send('OnTriggerEnter');self.assertEqual(self.logs,['0'])
        self.logs.clear();self.send('OnTriggerEnter',NS(name='player',is_player=True))
        self.assertEqual(self.logs,['1','2'])
        self.logs.clear();self.send('OnTriggerEnter',NS(name='Wrong',is_player=False))
        self.assertEqual(self.logs,[])

    def test_regenerate_old_script_preserves_custom_handler_and_fires_each_once(self):
        old='''from engine_runtime import Behaviour
# region MYENGINE_BLUEPRINT
def _bp_start(self, dt=0.0): pass
# endregion MYENGINE_BLUEPRINT
class Script(Behaviour):
    def start(self): _bp_start(self)
    def on_trigger_enter(self, other): self.world.log("manual: " + other.name)
# my handwritten code stays here
'''
        self.path.write_text(old,encoding='utf-8')
        save_python(self.path,events_graph(['OnTriggerEnter']))
        self.assertIn('# my handwritten code stays here',self.path.read_text())
        self.assertTrue(self.binding.reload());self.send('OnTriggerEnter')
        self.assertEqual(self.logs,['manual: Cube','OnTriggerEnter'])
        save_python(self.path,events_graph(['OnTriggerExit']))
        self.assertTrue(self.binding.reload());self.logs.clear()
        self.send('OnTriggerEnter');self.send('OnTriggerExit')
        self.assertEqual(self.logs,['manual: Cube','OnTriggerExit'])

    def test_start_disabled_and_trust_gates_apply_to_blueprint_callbacks(self):
        self.bind(events_graph(['OnTriggerEnter']),defer=True)
        self.send('OnTriggerEnter');self.assertEqual(self.logs,[])
        self.binding.call('start')
        for obj,field in [(self.binding,'enabled'),(self.binding.instance,'enabled'),
                          (self.entity,'script_trusted'),(self.world,'scripts_allowed')]:
            setattr(obj,field,False);self.send('OnTriggerEnter');setattr(obj,field,True)
        self.assertEqual(self.logs,[])
        self.send('OnTriggerEnter');self.assertEqual(self.logs,['OnTriggerEnter'])

    def test_fixed_delta_time_available_to_event_chain(self):
        graph={'format':1,'nodes':[{'id':'e','type':'OnTriggerStay'},
               {'id':'dt','type':'DeltaTime'},{'id':'move','type':'Move'}],
               'links':[['e','next','move','in'],['dt','value','move','x']]}
        moved=[];self.entity.move=lambda *args:moved.append(args)
        self.bind(graph);self.send('OnTriggerStay')
        self.assertEqual(moved,[(.02,0,0,0)])

    def test_invalid_filters_rejected_and_callback_failure_disables_binding(self):
        for filters in ({'otherName':12},{'playerOnly':'false'}):
            with self.assertRaises(ValueError):generated_source(events_graph(**filters))
        self.bind(events_graph(['OnTriggerEnter']))
        def fail(text):raise RuntimeError('expected test failure')
        self.world.log=fail
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            self.send('OnTriggerEnter')
        self.assertFalse(self.binding.enabled)


@unittest.skipUnless(sys.platform=='linux','Uses the shipped native Linux physics core')
class NativePhysicsTests(unittest.TestCase):
    def setUp(self):
        from engine_linux import LinuxCore
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.core=LinuxCore(ROOT,window=False);self.world=World(self.core,self.root)
        self.world.camera.position=(100,100,100);self.world.scripts_allowed=True
        self.world.physics.gravity=(0,0,0);self.logs=[];self.world.log=self.logs.append
        (self.root/'events.py').write_text(generated_source(events_graph())[0],encoding='utf-8')
    def tearDown(self):
        self.world.shutdown();self.core.close();self.temp.cleanup()
    def pair(self,trigger):
        self.owner=self.world.instantiate(name='Zone',collider={'size':[2,2,2],'isTrigger':trigger},scripts=['events.py'])
        self.other=self.world.instantiate(name='Cube',position=(.5,0,0),collider={'size':[1,1,1]},
                                         rigidbody=None if trigger else {'use_gravity':False})
    def tick(self):self.world.tick(self.world.physics.fixed_delta_time,bytes(256))

    def test_native_trigger_enter_stay_exit_without_rigidbody_and_no_repeats(self):
        self.pair(True);self.tick();self.tick()
        self.other.position=(10,0,0);self.tick();self.tick()
        self.assertEqual(self.logs,['OnTriggerEnter','OnTriggerStay','OnTriggerExit'])

    def test_native_collision_enter_stay_exit_and_trigger_mode_change(self):
        self.pair(False);self.tick()
        self.other.rigidbody.teleport((.5,0,0));self.tick()
        self.other.rigidbody.teleport((10,0,0));self.tick()
        self.assertEqual(self.logs,['OnCollisionEnter','OnCollisionStay','OnCollisionExit'])
        self.logs.clear();self.owner.collider.isTrigger=True
        self.other.rigidbody.teleport((.5,0,0));self.tick()
        self.assertEqual(self.logs,['OnTriggerEnter'])

    def test_player_filter_and_disable_collider_exit(self):
        (self.root/'events.py').write_text(generated_source(events_graph(playerOnly=True))[0],encoding='utf-8')
        self.pair(True);self.world.camera.position=(0,0,0);self.tick()
        self.assertEqual(self.logs,['OnTriggerEnter'])
        self.owner.collider.enabled=False;self.tick();self.tick()
        self.assertEqual(self.logs,['OnTriggerEnter','OnTriggerExit'])

    def test_destroy_other_reports_exit_and_destroy_owner_does_not_run_its_script(self):
        self.pair(True);self.tick();self.other.destroy();self.tick()
        self.assertEqual(self.logs,['OnTriggerEnter','OnTriggerExit'])
        self.other=self.world.instantiate(name='NewCube',collider={'size':[1,1,1]})
        self.tick();self.owner.destroy();self.tick()
        self.assertEqual(self.logs,['OnTriggerEnter','OnTriggerExit','OnTriggerEnter'])


if __name__=='__main__':unittest.main()
