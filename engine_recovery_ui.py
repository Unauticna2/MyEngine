"""Recovery picker in a separate Windows process; download/extract off the game thread."""
from pathlib import Path
import json
import os
import subprocess
import tempfile
import threading
import time
from engine_releases import recovery_config,restore_release
from engine_scene import atomic_json

class RecoveryTask:
    def __init__(self, root):
        self.root=Path(root).resolve();self.done=threading.Event();self.cancelled=threading.Event();self.process=None
        self.thread=threading.Thread(target=self.run,name='release-restore',daemon=True);self.thread.start()
    def run(self):
        from engine_window_menu import message
        try:
            config=recovery_config(self.root)
            config.update(destination=str(Path.home()/'Downloads'/'MyEngineRestored'),isGame=(self.root/'build.json').is_file())
            script=Path(__file__).resolve().parent/'tools/release_picker.ps1'
            if not script.is_file():raise FileNotFoundError('Установи tools/release_picker.ps1 из обновления R25.')
            with tempfile.TemporaryDirectory(prefix='myengine-recovery-') as folder:
                request=Path(folder)/'request.json';result=Path(folder)/'result.json'
                request.write_text(json.dumps(config,ensure_ascii=False),encoding='utf-8')
                if self.cancelled.is_set():return
                shell=Path(os.environ.get('SystemRoot','C:/Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
                self.process=subprocess.Popen([str(shell),'-NoProfile','-STA','-ExecutionPolicy','Bypass','-File',str(script),
                    '-RequestPath',str(request),'-ResultPath',str(result)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
                    creationflags=0x08000000)
                _,error=self.process.communicate()
                if self.cancelled.is_set():return
                if self.process.returncode:raise RuntimeError('Окно восстановления: '+error.decode(errors='replace')[-2000:])
                if not result.exists():return
                choice=json.loads(result.read_text(encoding='utf-8-sig'))
                last_log=[0.0]
                def progress(text):
                    if self.cancelled.is_set():raise RuntimeError('Восстановление отменено при закрытии программы.')
                    if time.monotonic()-last_log[0]>=1:
                        print('RESTORE:',text);last_log[0]=time.monotonic()
                destination=restore_release(choice['repository'],choice['tag'],choice['asset'],choice['destination'],progress)
                if choice.get('remember') and not config['isGame']:
                    atomic_json(self.root/'engine-release.json',{k:choice[k] for k in ('repository','tag','asset')})
                if not self.cancelled.is_set():
                    os.startfile(str(destination))
                    message('Версия восстановлена:\n'+str(destination)+'\n\nЗапусти EXE из этой папки. Текущая установка не изменена.')
        except Exception as ex:
            if not self.cancelled.is_set():message(str(ex),True)
        finally:self.done.set()
    def close(self):
        self.cancelled.set()
        if self.process is not None and self.process.poll() is None:self.process.terminate()
