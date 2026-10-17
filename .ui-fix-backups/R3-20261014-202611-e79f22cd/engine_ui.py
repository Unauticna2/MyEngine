"""Slide-based 2D UI. Data/actions are platform independent; native draw uses GL 2.1."""
from pathlib import Path
from copy import deepcopy
import math,json
from engine_assets import asset_path,finite

def load_document(path):
    path=Path(path)
    if path.stat().st_size>8*1024*1024:raise ValueError('UI document is too large')
    data=json.loads(path.read_text(encoding='utf-8-sig'));validate(data);return data

def validate(data):
    if not isinstance(data,dict) or data.get('format')!=1 or data.get('kind')!='MyEngine.UI':raise ValueError('Not a MyEngine UI document')
    if not 1<=finite(data.get('width',0))<=16384 or not 1<=finite(data.get('height',0))<=16384:raise ValueError('Invalid UI dimensions')
    slides=data.get('slides',[])
    if not isinstance(slides,list) or len(slides)>256:raise ValueError('UI limit: 256 slides')
    ids=set()
    for slide in slides:
        sid=str(slide['id'])
        if sid in ids:raise ValueError('Duplicate slide '+sid)
        ids.add(sid);elements=slide.get('elements',[]);element_ids=set()
        if len(elements)>2048:raise ValueError('Slide limit: 2048 elements')
        for e in elements:
            eid=str(e['id'])
            if eid in element_ids:raise ValueError('Duplicate UI element '+eid)
            element_ids.add(eid)
            if len(e['rect'])!=4 or any(not math.isfinite(float(v)) for v in e['rect']) or min(e['rect'][2:])<=0:raise ValueError('Invalid UI rect')
            if 'imageRect' in e:
                r=e['imageRect']
                if not isinstance(r,list) or len(r)!=4 or any(not math.isfinite(float(v)) for v in r) or min(r[2:])<=0:raise ValueError('Invalid UI imageRect')
            for a in e.get('animations',[]):validate_animation(a)
        for a in slide.get('animations',[]):
            if str(a['element']) not in element_ids:raise ValueError('Animation refers to missing element')
            validate_animation(a)
    json.dumps(data,allow_nan=False)

def validate_animation(a):
    if a.get('kind') not in ('fade','appear','fly','zoom','spin','move'):raise ValueError('Unknown UI animation')
    if finite(a.get('duration',1))<0 or finite(a.get('delay',0))<0 or not 0<=int(a.get('group',0))<=1024:raise ValueError('Invalid animation timing')

def image_paths(data):
    for slide in data['slides']:
        if slide.get('background'):yield slide['background']
        for e in slide.get('elements',[]):
            if e.get('image'):yield e['image']
            yield from e.get('frames',[])

class SlideUI:
    def __init__(self,world,path):
        self.world=world;self.path=asset_path(world.root,path);self.data=load_document(self.path);self.base=self.path.parent
        self.slides={str(s['id']):deepcopy(s) for s in self.data['slides']};self.enabled=True;self.active=None;self.time=0.;self.groups={0:0.};self.last_down=False;self.pressed_element=None;self.renderer=None
        self.images={}
        for p in dict.fromkeys(image_paths(self.data)):
            target=(self.base/p).resolve();target.relative_to(world.root)
            self.images[p]=target.relative_to(world.root).as_posix()
        sid=str(self.data.get('startSlide',''))
        if sid not in self.slides or not self.slides[sid].get('enabled',True):sid=next((k for k,s in self.slides.items() if s.get('enabled',True)),None)
        if sid is not None:self.show_slide(sid,run_actions=False)
    def show_slide(self,slide,run_actions=True):
        sid=str(slide)
        if sid not in self.slides:raise KeyError('Unknown slide '+sid)
        if not self.slides[sid].get('enabled',True):return False
        self.active=sid;self.enabled=True;self.time=0.;self.groups={0:0.};self.pressed_element=None
        if run_actions:self.actions(self.slides[sid].get('onEnter',[]))
        return True
    def set_slide_enabled(self,slide,enabled):
        sid=str(slide);self.slides[sid]['enabled']=bool(enabled)
        if self.active==sid and not enabled:self.active=None
    def set_element_enabled(self,element,enabled,slide=None):
        s=self.slides[str(slide or self.active)]
        next(e for e in s['elements'] if str(e['id'])==str(element))['enabled']=bool(enabled)
    def next_slide(self):
        ids=list(self.slides);start=ids.index(self.active)+1 if self.active in ids else 0
        for sid in ids[start:]:
            if self.show_slide(sid):return True
        return False
    def advance_animation(self):
        if self.active is None:return
        slide=self.slides[self.active]
        all_a=list(slide.get('animations',[]))+[a for e in slide['elements'] for a in e.get('animations',[])]
        pending=sorted({int(a.get('group',0)) for a in all_a}-set(self.groups))
        if pending:self.groups[pending[0]]=self.time
    def pose(self,e):
        x,y,w,h=map(float,e['rect']);angle=finite(e.get('rotation',0));alpha=finite(e.get('opacity',1));scale=1.
        animations=list(e.get('animations',[]))+[a for a in self.slides[self.active].get('animations',[]) if str(a['element'])==str(e['id'])]
        for a in animations:
            start=self.groups.get(int(a.get('group',0)));duration=max(1e-6,float(a.get('duration',1)))
            t=-1 if start is None else self.time-start-float(a.get('delay',0));p=max(0,min(1,t/duration));ex=bool(a.get('exit',False));kind=a['kind'];v=(1-p) if ex else p
            if kind in ('fade','appear'):alpha*=v if kind=='fade' else float(t>=0) if not ex else float(t<0)
            elif kind=='zoom':scale*=v
            elif kind=='fly':
                dx,dy=a.get('offset',(0,self.data['height']));x+=float(dx)*(p if ex else 1-p);y+=float(dy)*(p if ex else 1-p)
            elif kind=='spin':angle+=float(a.get('degrees',360))*p
            elif kind=='move':dx,dy=a.get('offset',(0,0));x+=float(dx)*p;y+=float(dy)*p
            if t<0 and kind in ('fade','appear','zoom','fly') and not ex:alpha=0
        x+=w*(1-scale)*.5;y+=h*(1-scale)*.5;w*=scale;h*=scale
        return x,y,w,h,angle,max(0,min(1,alpha))
    def transform(self,width,height):
        scale=min(width/self.data['width'],height/self.data['height']);return scale,(width-self.data['width']*scale)*.5,(height-self.data['height']*scale)*.5
    def hit(self,px,py,width,height):
        if not self.enabled or self.active is None:return None
        if width<=0 or height<=0:return None
        scale,ox,oy=self.transform(width,height);px=(px-ox)/scale;py=(py-oy)/scale
        for e in reversed(self.slides[self.active]['elements']):
            if not e.get('enabled',True) or not e.get('onClick'):continue
            x,y,w,h,angle,alpha=self.pose(e)
            if alpha<=.01:continue
            a=math.radians(-angle);dx=px-x-w*.5;dy=py-y-h*.5
            lx=math.cos(a)*dx-math.sin(a)*dy;ly=math.sin(a)*dx+math.cos(a)*dy
            if abs(lx)<=w*.5 and abs(ly)<=h*.5:return e
        return None
    def update(self,dt,pointer=None):
        if not self.enabled or self.active is None:self.last_down=False;return False
        self.time+=max(0,float(dt))
        if pointer is None:return bool(self.slides[self.active].get('modal',False))
        x,y,down,width,height=pointer;hit=self.hit(x,y,width,height)
        if down and not self.last_down:self.pressed_element=hit
        if self.last_down and not down:
            if hit is not None and hit is self.pressed_element:self.actions(hit.get('onClick',[]))
            elif self.pressed_element is None and 0<=x<width and 0<=y<height:self.advance_animation()
            self.pressed_element=None
        self.last_down=bool(down)
        return bool(hit or self.pressed_element or self.active and self.slides[self.active].get('modal',False))
    def actions(self,actions):
        self._action_depth=getattr(self,'_action_depth',0)+1
        try:
            if self._action_depth>16:raise ValueError('UI onEnter actions form a recursive slide loop')
            self._actions(actions)
        finally:self._action_depth-=1
    def _actions(self,actions):
        for a in list(actions):
            kind=a['action']
            if kind=='slide':self.show_slide(a['slide'])
            elif kind=='next':self.next_slide()
            elif kind=='ui':self.enabled=bool(a['enabled'])
            elif kind=='enableSlide':self.set_slide_enabled(a['slide'],a['enabled'])
            elif kind=='element':self.set_element_enabled(a['id'],a['enabled'],a.get('slide'))
            elif kind=='scene':self.world.load_scene(a['path'])
            elif kind in ('script','call'):
                entity=self.world.find(a['object'])
                if entity is None:raise ValueError('UI target not found: '+a['object'])
                if not self.world.scripts_allowed or not getattr(entity,'script_trusted',True):continue
                if kind=='script':
                    path=asset_path(self.world.root,a['path']);bindings=[b for b in entity.scripts if b.path==path]
                    if not bindings and a.get('enabled',True):entity.add_script(a['path']);bindings=[b for b in entity.scripts if b.path==path]
                    for b in bindings:
                        b.enabled=bool(a.get('enabled',True))
                        if b.instance is not None:b.instance.enabled=b.enabled
                        if b.enabled and not b.started:b.call('start')
                else:
                    name=a['method']
                    if not isinstance(name,str) or name.startswith('_') or not name.isidentifier():raise ValueError('Use a public script method')
                    for b in entity.scripts:
                        if not a.get('path') or b.path==asset_path(self.world.root,a['path']):b.call(name,*a.get('args',[]))
            else:raise ValueError('Unknown UI action '+kind)
    def draw(self):
        if not self.enabled or self.active is None:return
        if self.renderer is None:
            from engine_ui_gl import UIRenderer
            self.renderer=UIRenderer()
        self.renderer.draw(self)
