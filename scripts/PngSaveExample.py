"""F1: screenshot save; F2: restore only the fields selected in GameSave."""
from dataclasses import dataclass,field
from pathlib import Path
from engine_runtime import Behaviour
from PNGJSONUnitylity import PNGJSONUnitylity

@dataclass
class GameSave:
    position:list=field(default_factory=lambda:[0,2,7])
    camera_w:float=0.
    needs:list=field(default_factory=lambda:[100]*6)

class Script(Behaviour):
    def start(self):
        self.needs=[100]*6;self.pending=None
        # User saves belong in a writable user directory, not Program Files / game assets.
        self.path=Path.home()/'MyEngineSaves'/'save.png'
    def save(self):
        if self.pending and not self.pending.done():return
        data=GameSave(list(self.world.camera.position),self.world.camera.w,list(self.needs))
        self.pending=PNGJSONUnitylity.ToPngJson(self.path,data)
    def load(self):
        if not self.path.exists():return
        data=PNGJSONUnitylity.FromPngJson(self.path,GameSave)
        if len(data.position)!=3 or len(data.needs)!=6:raise ValueError('Invalid game save')
        self.world.camera.position=data.position;self.world.camera.w=data.camera_w;self.needs=data.needs
    def update(self,dt):
        if self.world.input.pressed('F1'):self.save()
        if self.world.input.pressed('F2'):self.load()
        if self.pending and self.pending.done():
            try:self.world.log('PNG saved:',self.pending.result())
            except Exception as ex:self.world.log('Save failed:',ex)
            self.pending=None
    def on_ui_close(self):self.world.log('UI hidden; F1 saves, F2 restores GameSave.')
