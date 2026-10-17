"""Authoring EXE opens Hub; explicit scenes and exported players stay players."""
from dataclasses import dataclass
from pathlib import Path
import argparse,configparser,json,os,subprocess,sys,tempfile,time

@dataclass(frozen=True)
class Launch:
    mode:str
    root:Path
    scene:Path|None=None
    editor:tuple|None=None

class Parser(argparse.ArgumentParser):
    def error(self,message):raise ValueError('MyEngine launch: '+message)

def resolve_launch(engine_root,args):
    engine=Path(engine_root).resolve()
    parser=Parser(add_help=False)
    parser.add_argument('scene',nargs='?');parser.add_argument('--project',type=Path)
    parser.add_argument('--editor',nargs=2,metavar=('PORT','TOKEN'));parser.add_argument('--hub',action='store_true')
    options=parser.parse_args(list(args));root=options.project.resolve() if options.project else engine
    if options.hub:
        if options.scene or options.project or options.editor:raise ValueError('--hub нельзя совмещать со сценой, --project или --editor.')
        return Launch('hub',engine)
    if not options.scene and not options.project and not options.editor and not (engine/'build.json').is_file():
        return Launch('hub',engine)
    if options.editor:
        if not options.scene:raise ValueError('--editor требует путь к preview-сцене.')
        try:port=int(options.editor[0])
        except ValueError:raise ValueError('Editor port must be a number') from None
        if not 1<=port<=65535:raise ValueError('Editor port must be 1..65535')
    scene=options.scene
    if scene is None:
        manifest=root/'build.json'
        if not manifest.is_file():manifest=root/'project.myengine.json'
        scene=json.loads(manifest.read_text(encoding='utf-8-sig'))['mainScene'] if manifest.is_file() else 'map.json'
        if not isinstance(scene,str) or not scene.strip():raise ValueError('mainScene must be a nonempty scene path')
    return Launch('editor' if options.editor else 'game',root,(root/scene).resolve(),tuple(options.editor) if options.editor else None)

def python_for_hub(engine_root):
    """Never relaunch sys.executable: inside CPython embedding it is MyEngine2.exe."""
    root=Path(engine_root).resolve();homes=[];ini=root/'python.ini'
    if ini.is_file():
        config=configparser.ConfigParser(interpolation=None);config.read(ini,encoding='utf-16')
        home=Path(config.get('Python','Home'));homes.append((root/home).resolve())
    homes.append(Path(sys.base_prefix).resolve())
    for home in dict.fromkeys(homes):
        for name in ('pythonw.exe','python.exe'):
            candidate=home/name
            if candidate.is_file():return candidate
    raise FileNotFoundError('Для Hub не найден pythonw.exe / python.exe. Запусти setup_python.cmd с обычным Python 3.11–3.13, установленным с Tcl/Tk.')

class HubLaunch:
    """Nonblocking handoff: keep the EXE alive until the Hub window is ready."""
    def __init__(self,engine_root,*,timeout=30):
        root=Path(engine_root).resolve();script=root/'MyEngineHub.py'
        if not script.is_file():raise FileNotFoundError('MyEngineHub.py отсутствует рядом с движком. Установи обновление целиком; Hub не входит в собранную игру.')
        interpreter=python_for_hub(root)
        self.process=None;self.handed_off=False;self.closed=False;self.timeout=timeout;self.started=time.monotonic()
        folder=Path(os.environ.get('LOCALAPPDATA') or tempfile.gettempdir())/'MyEngine2/Hub'
        folder.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(prefix='launch-',dir=folder)
        self.ready=Path(self.temp.name)/'ready';self.log_path=folder/('launch-'+Path(self.temp.name).name+'.log')
        environment=os.environ.copy();environment['MYENGINE_HUB_READY_FILE']=str(self.ready)
        environment.pop('MYENGINE_LOG_DIR',None)
        options={'cwd':str(root),'env':environment,'stdin':subprocess.DEVNULL,'close_fds':True}
        if sys.platform=='win32':options['creationflags']=subprocess.CREATE_NO_WINDOW
        try:
            with self.log_path.open('wb') as log:
                self.process=subprocess.Popen([str(interpreter),str(script)],stdout=log,stderr=log,**options)
        except BaseException:self.temp.cleanup();raise
    def poll(self):
        if self.handed_off:return True
        if self.closed:return False
        if self.ready.is_file():
            self.handed_off=True;self.temp.cleanup();return True
        code=self.process.poll()
        if code is not None:
            raise RuntimeError(f'Hub завершился до открытия окна (код {code}). Лог: {self.log_path}')
        if time.monotonic()-self.started>self.timeout:
            raise RuntimeError(f'Hub не открыл окно за {self.timeout} секунд. Лог: {self.log_path}')
        return False
    def close(self):
        if self.closed:return
        self.closed=True
        if not self.handed_off and self.process is not None and self.process.poll() is None:
            self.process.terminate()  # Only the unready child started by this launch.
        self.temp.cleanup()
