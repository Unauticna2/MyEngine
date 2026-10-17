"""Launch routing and the asynchronous EXE -> Hub process handoff."""
import json,os,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
import engine_startup as startup
import engine_runtime as runtime

class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def manifest(self,folder,name,scene):
        folder.mkdir(parents=True,exist_ok=True);(folder/name).write_text(json.dumps({'mainScene':scene}))
    def test_double_click_opens_hub_even_when_old_map_exists(self):
        (self.root/'map.json').write_text('{"model":[]}')
        self.assertEqual(startup.resolve_launch(self.root,[]).mode,'hub')
    def test_exported_player_uses_build_main_scene_without_hub(self):
        self.manifest(self.root,'build.json','scenes/menu.json')
        launch=startup.resolve_launch(self.root,[])
        self.assertEqual(launch.mode,'game');self.assertEqual(launch.scene,self.root/'scenes/menu.json')
    def test_explicit_scene_keeps_demo_commands_working(self):
        launch=startup.resolve_launch(self.root,['map.json'])
        self.assertEqual(launch.mode,'game');self.assertEqual(launch.scene,self.root/'map.json')
    def test_project_launch_uses_its_start_scene(self):
        project=self.root/'Проект с пробелами';self.manifest(project,'project.myengine.json','scenes/menu.json')
        launch=startup.resolve_launch(self.root,['--project',str(project)])
        self.assertEqual(launch.root,project);self.assertEqual(launch.scene,project/'scenes/menu.json')
    def test_editor_preview_and_token_unchanged(self):
        project=self.root/'Project';preview=project/'.myengine/preview.json'
        launch=startup.resolve_launch(self.root,[str(preview),'--project',str(project),'--editor','43512','token'])
        self.assertEqual(launch.mode,'editor');self.assertEqual(launch.editor,('43512','token'));self.assertEqual(launch.scene,preview)
    def test_explicit_hub_and_invalid_mixed_flags(self):
        self.manifest(self.root,'build.json','scenes/menu.json')
        self.assertEqual(startup.resolve_launch(self.root,['--hub']).mode,'hub')
        for args in [['--hub','map.json'],['--hub','--project','.'],['--editor','1234','token'],['map.json','--editor','abc','token']]:
            with self.assertRaises(ValueError):startup.resolve_launch(self.root,args)

class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        (self.root/'MyEngineHub.py').write_text('# hub fixture')
        self.home=self.root/'Python & тест';self.home.mkdir();(self.home/'pythonw.exe').write_bytes(b'fixture')
        (self.home/'python.exe').write_bytes(b'fixture')
        (self.root/'python.ini').write_text(f'[Python]\nHome={self.home}\n',encoding='utf-16')
        env=patch.dict(os.environ,{'LOCALAPPDATA':str(self.root/'Local App Data')});env.start();self.addCleanup(env.stop)
    def test_uses_configured_pythonw_not_embedded_engine_exe(self):
        with patch.object(sys,'executable',str(self.root/'MyEngine2.exe')):
            self.assertEqual(startup.python_for_hub(self.root),self.home/'pythonw.exe')
        (self.home/'pythonw.exe').unlink();self.assertEqual(startup.python_for_hub(self.root),self.home/'python.exe')
    def test_success_waits_for_ready_without_blocking_and_does_not_kill_hub(self):
        process=Mock();process.poll.return_value=None
        with patch.object(startup.subprocess,'Popen',return_value=process) as popen:
            job=startup.HubLaunch(self.root)
        self.addCleanup(job.close)
        argv=popen.call_args.args[0];self.assertEqual(argv,[str(self.home/'pythonw.exe'),str(self.root/'MyEngineHub.py')])
        self.assertFalse(popen.call_args.kwargs.get('shell',False));self.assertFalse(job.poll())
        process.wait.assert_not_called();job.ready.write_text('ready')
        self.assertTrue(job.poll());job.close();process.terminate.assert_not_called()
        self.assertFalse(job.ready.parent.exists())
    def test_failure_reports_log_and_can_cancel_only_its_unready_process(self):
        process=Mock();process.poll.return_value=None
        with patch.object(startup.subprocess,'Popen',return_value=process):job=startup.HubLaunch(self.root,timeout=1)
        self.addCleanup(job.close);job.started-=2
        with self.assertRaisesRegex(RuntimeError,'Лог:'):job.poll()
        job.close();process.terminate.assert_called_once();self.assertFalse(job.ready.parent.exists())
    def test_child_exit_is_not_reported_as_success(self):
        process=Mock();process.poll.return_value=1
        with patch.object(startup.subprocess,'Popen',return_value=process):job=startup.HubLaunch(self.root)
        self.addCleanup(job.close)
        with self.assertRaisesRegex(RuntimeError,'код 1'):job.poll()
    def test_spawn_failure_removes_handshake_files(self):
        with patch.object(startup.subprocess,'Popen',side_effect=OSError('cannot start')):
            with self.assertRaises(OSError):startup.HubLaunch(self.root)
        self.assertFalse([p for p in (self.root/'Local App Data/MyEngine2/Hub').iterdir() if p.is_dir()])
    def test_real_python_child_confirms_ready_and_inherits_engine_directory(self):
        # Real subprocess/IPC, using a headless fixture instead of a Tk window.
        import time
        (self.root/'MyEngineHub.py').write_text(
            'import os,json\nfrom pathlib import Path\n'
            'Path("child.json").write_text(json.dumps({"cwd":os.getcwd()}))\n'
            'Path(os.environ["MYENGINE_HUB_READY_FILE"]).write_text("ready")\n')
        with patch.object(startup,'python_for_hub',return_value=Path(sys.executable)):job=startup.HubLaunch(self.root)
        self.addCleanup(job.close)
        end=time.monotonic()+5
        while not job.poll():
            self.assertLess(time.monotonic(),end);time.sleep(.01)
        self.assertEqual(job.process.wait(timeout=2),0)
        self.assertEqual(json.loads((self.root/'child.json').read_text())['cwd'],str(self.root))
        job.close()

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        for name in ('_world','_editor','_hub_launch','_launch_core'):
            p=patch.object(runtime,name,None);p.start();self.addCleanup(p.stop)
    def test_start_hub_never_creates_world_or_loads_map_and_quits_after_ready(self):
        core=Mock();core.arguments.return_value=[];job=Mock();job.poll.side_effect=[False,True]
        with patch.object(runtime,'NativeCore',return_value=core),patch.object(runtime,'World') as world,patch.object(startup,'HubLaunch',return_value=job):
            runtime.start();world.assert_not_called();core.hide_window.assert_called_once()
            runtime.frame();core.request_quit.assert_not_called();runtime.draw()
            runtime.frame();core.request_quit.assert_called_once();job.close.assert_called_once()
            runtime.frame();runtime.shutdown() # Native frame can race the posted WM_CLOSE.
    def test_runtime_hub_failure_closes_child_and_propagates_error(self):
        job=Mock();job.poll.side_effect=RuntimeError('Hub error');runtime._hub_launch=job
        with self.assertRaisesRegex(RuntimeError,'Hub error'):runtime.frame()
        job.close.assert_called_once();self.assertIsNone(runtime._hub_launch)
    def test_actual_start_uses_build_scene_without_launching_hub(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'build.json').write_text('{"mainScene":"scenes/menu.json"}')
            core=Mock();core.arguments.return_value=[];world=Mock();world.root=root
            with patch.object(runtime,'__file__',str(root/'engine_runtime.py')),patch.object(runtime,'NativeCore',return_value=core),patch.object(runtime,'World',return_value=world),patch.object(startup,'HubLaunch') as hub,patch.object(runtime.os,'chdir'),patch.object(sys,'path',list(sys.path)):
                runtime.start();hub.assert_not_called();world.load.assert_called_once_with(root/'scenes/menu.json');core.hide_window.assert_not_called()

if __name__=='__main__':unittest.main()
