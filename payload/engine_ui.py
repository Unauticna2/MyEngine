"""Slide-based 2D UI. Data/actions are platform independent; native draw uses GL 2.1."""
from pathlib import Path
from copy import deepcopy
import math,json
from engine_assets import asset_path,finite
from engine_ui_effects import ANIMATION_MODES, transition_settings

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
        transition_settings(slide.get('transition'))
        if 'advanceAfter' in slide and finite(slide['advanceAfter'])<0:raise ValueError('Invalid slide advance time')
        if len(elements)>2048:raise ValueError('Slide limit: 2048 elements')
        for e in elements:
            from engine_ui_content import validate_content
            try:validate_content(e)
            except ValueError as ex:
                raise ValueError(f'Слайд {sid}, элемент {e.get("id", "?")}: {ex}') from ex
            eid=str(e['id'])
            if eid in element_ids:raise ValueError('Duplicate UI element '+eid)
            element_ids.add(eid)
            if e.get('animationMode','imported') not in ANIMATION_MODES:raise ValueError('Invalid animation mode')
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

def image_paths(data, *, include_background=True):
    for slide in data['slides']:
        if include_background and slide.get('background'):yield slide['background']
        for e in slide.get('elements',[]):
            if e.get('image'):yield e['image']
            if e.get('textSlot',{}).get('image'):yield e['textSlot']['image']
            yield from e.get('frames',[])

class SlideUI:
    def __init__(self,world,path,*,show_background=False):
        self.world=world;self.path=asset_path(world.root,path);self.data=load_document(self.path);self.base=self.path.parent
        self.slides={str(s['id']):deepcopy(s) for s in self.data['slides']};self.enabled=True;self.active=None;self.time=0.;self.groups={0:0.};self.last_down=False;self.pressed_element=None;self.renderer=None
        from engine_ui_content import UIContent
        self.content=UIContent(self);self._viewport=(self.data['width'],self.data['height']);self._video_autoplay_done=False
        self._blueprints={}
        self._transition=None;self._element_starts={};self._manual_starts={};self._triggers={};self._pending_click=None
        from engine_ui_scaling import normalized
        self.scale_settings=normalized(getattr(world,'ui_scale',None))
        self.assets=None;self._pending_slide=None;self._warming=False
        if hasattr(getattr(world,'resources',None),'cache'):
            from engine_ui_assets import UIAssets
            self.assets=UIAssets(world)
        self.show_background=show_background
        sid=str(self.data.get('startSlide',''))
        if sid not in self.slides or not self.slides[sid].get('enabled',True):sid=next((k for k,s in self.slides.items() if s.get('enabled',True)),None)
        if sid is not None:self.show_slide(sid,run_actions=False)
    @property
    def show_background(self):return self._show_background
    @show_background.setter
    def show_background(self,value):
        # Old imports keep their background field on disk. Hidden backgrounds
        # are neither resolved nor uploaded; no asset migration is required.
        images={}
        for p in dict.fromkeys(image_paths(self.data,include_background=bool(value))):
            target=(self.base/p).resolve();target.relative_to(self.world.root)
            images[p]=target.relative_to(self.world.root).as_posix()
        self._show_background=bool(value);self.images=images
        if self.assets:self.assets.request(self.slide_images(self.active),priority=True)
    def slide_images(self,sid):
        if sid is None:return []
        slide=self.slides[str(sid)]
        return list(dict.fromkeys(self.images[p] for p in image_paths({'slides':[slide]},include_background=self.show_background)))
    def assets_ready(self,sid):
        return self.assets is None or self.assets.ready(self.slide_images(sid))
    def preload_adjacent(self):
        if self.assets is None or self.active is None:return
        ids=[sid for sid,s in self.slides.items() if s.get('enabled',True)]
        if self.active not in ids:return
        i=ids.index(self.active)
        for j in (i+1,i-1):
            if 0<=j<len(ids):self.assets.request(self.slide_images(ids[j]))
    def close(self):
        self.content.close()
        if self.assets:self.assets.close()
    @property
    def loading(self):
        sid=self._pending_slide[0] if self._pending_slide else self.active
        return sid is not None and not self.assets_ready(sid)
    def draw_elements(self):
        slide=self.slides[self.active];elements=slide['elements']
        if self.show_background and slide.get('background'):
            return [{'id':'_background','image':slide['background'],
                     'rect':[0,0,self.data['width'],self.data['height']]},*elements]
        return elements
    def show_slide(self,slide,run_actions=True,transition=None,duration=None,direction=None):
        sid=str(slide)
        if sid not in self.slides:raise KeyError('Unknown slide '+sid)
        if not self.slides[sid].get('enabled',True):return False
        if self.assets:
            self.assets.request(self.slide_images(sid),priority=True)
            if self.active is not None and not self.assets_ready(sid):
                self._pending_slide=(sid,run_actions,transition,duration,direction)
                return True
        self.content.stop_video();self._video_autoplay_done=False
        self._pending_slide=None
        settings=dict(self.slides[sid].get('transition') or {})
        if transition not in (None,'imported'):
            settings={'kind':transition,'duration':.35 if duration is None else duration,'direction':direction or 'left'}
        settings=transition_settings(settings)
        outgoing=self.render_items() if self.enabled and self.active is not None and self.active!=sid else []
        outgoing=[(dict(e,image=e['frames'][self.frame_index(e)],frames=[]),pose)
                  if e.get('frames') else (e,pose) for e,pose in outgoing]
        self.active=sid;self.enabled=True;self.time=0.;self.groups={0:0.};self.pressed_element=None
        self._element_starts={};self._manual_starts={};self._triggers={}
        self._pending_click=None
        self._transition={'items':outgoing,'settings':settings,'time':0.} if outgoing and settings['kind']!='none' and settings['duration']>0 else None
        if run_actions:self.actions(self.slides[sid].get('onEnter',[]))
        self.preload_adjacent()
        return True
    def set_slide_enabled(self,slide,enabled):
        sid=str(slide);self.slides[sid]['enabled']=bool(enabled)
        if self.active==sid and not enabled:self.active=None
    def set_element_enabled(self,element,enabled,slide=None):
        s=self.slides[str(slide or self.active)]
        next(e for e in s['elements'] if str(e['id'])==str(element))['enabled']=bool(enabled)
    def next_slide(self,**transition):
        ids=list(self.slides);start=ids.index(self.active)+1 if self.active in ids else 0
        for sid in ids[start:]:
            if self.show_slide(sid,**transition):return True
        return False
    def previous_slide(self,**transition):
        ids=list(self.slides);start=ids.index(self.active) if self.active in ids else len(ids)
        for sid in reversed(ids[:start]):
            if self.show_slide(sid,**transition):return True
        return False
    def animations_for(self,e):
        return list(e.get('animations',[]))+[a for a in self.slides[self.active].get('animations',[]) if str(a['element'])==str(e['id'])]
    def play_animation(self,element,slide=None):
        if slide is not None and str(slide)!=self.active:return False
        eid=str(element)
        if not any(str(e['id'])==eid for e in self.slides[self.active]['elements']):raise KeyError('Unknown UI element '+eid)
        self._manual_starts[eid]=self.time;return True
    def has_click_animation(self,e):
        if e.get('animationMode')=='click':return True
        return any(str(a.get('triggerElement',''))==str(e['id']) for item in self.slides[self.active]['elements'] for a in self.animations_for(item)) or (e.get('animationMode','imported')=='imported' and any(int(a.get('group',0))>0 for a in self.animations_for(e)))
    def click_animation(self,e):
        eid=str(e['id'])
        if e.get('animationMode')=='click':self._element_starts[eid]=self.time
        for item in self.slides[self.active]['elements']:
            for a in self.animations_for(item):
                if str(a.get('triggerElement',''))==eid:self._triggers[str(a.get('triggerGroup',eid))]=self.time
        if e.get('animationMode','imported')=='imported':
            pending=sorted({int(a.get('group',0)) for a in self.animations_for(e) if not a.get('triggerElement')}-set(self.groups))
            if pending:self.groups[pending[0]]=self.time
    def animation_start(self,e,a):
        eid=str(e['id']);mode=e.get('animationMode','imported')
        if eid in self._manual_starts:return self._manual_starts[eid]
        if mode=='manual':return None
        if mode=='click':return self._element_starts.get(eid)
        if mode in ('auto','loop'):return 0.
        if a.get('triggerElement'):return self._triggers.get(str(a.get('triggerGroup',a['triggerElement'])))
        return self.groups.get(int(a.get('group',0)))
    def element_time(self,e):
        eid=str(e['id']);mode=e.get('animationMode','imported')
        if eid in self._manual_starts:return max(0,self.time-self._manual_starts[eid])
        if mode in ('click','manual'):return max(0,self.time-self._element_starts.get(eid,self.time))
        return self.time
    def frame_index(self,e):
        frames=e.get('frames',[]);index=int(self.element_time(e)*max(.01,float(e.get('fps',12))))
        return index%len(frames) if e.get('animationMode','imported') in ('imported','loop') else min(index,len(frames)-1)
    def animation_length(self,e):
        groups={}
        for a in self.animations_for(e):
            group=int(a.get('group',0));groups[group]=max(groups.get(group,0),float(a.get('delay',0))+float(a.get('duration',1)))
        return max(sum(groups.values()),len(e.get('frames',[]))/max(.01,float(e.get('fps',12))))
    def dispatch_click(self,slide,element):
        bindings=self.click_bindings(slide,element['id'])
        if bindings:
            for binding in bindings:binding.call('on_ui_click',slide,str(element['id']))
        else:
            try:self.content.click(slide,element)
            except Exception as ex:self.world.log('UI CONTENT: '+str(ex))
            self.actions(element.get('onClick',[]))
    def bind_blueprint(self,binding):
        self.unbind_blueprint(binding)
        if binding.ui_path and (Path(self.world.root)/binding.ui_path).resolve()!=self.path:return
        for slide,element in binding.ui_click_targets:
            if slide in self.slides and any(str(e['id'])==element for e in self.slides[slide]['elements']):
                self._blueprints.setdefault((slide,element),[]).append(binding)
            else:
                ids=', '.join(str(e['id']) for e in self.slides.get(slide,{}).get('elements',[])) or '(none)'
                self.world.log(f'UI CLICK NOT BOUND: {binding.path.name}: slide={slide!r}, element={element!r}. Available element IDs: {ids}. Open UI Blueprints to select the button.')
    def unbind_blueprint(self,binding):
        for key,bindings in list(self._blueprints.items()):
            kept=[b for b in bindings if b is not binding]
            if kept:self._blueprints[key]=kept
            else:del self._blueprints[key]
    def click_bindings(self,slide,element):
        if not getattr(self.world,'scripts_allowed',True) or getattr(self.world,'editor_mode',False):return ()
        return tuple(b for b in self._blueprints.get((str(slide),str(element)),())
            if b.started and b.enabled and b.instance is not None and getattr(b.instance,'enabled',True)
            and b.entity.active and not b.entity.destroyed and b.entity.script_trusted)
    def advance_animation(self):
        if self.active is None:return
        slide=self.slides[self.active]
        all_a=list(slide.get('animations',[]))+[a for e in slide['elements'] for a in e.get('animations',[])]
        pending=sorted({int(a.get('group',0)) for a in all_a if not a.get('triggerElement')}-set(self.groups))
        if pending:self.groups[pending[0]]=self.time;return True
        return False
    def pose(self,e):
        from engine_ui_layout import rect
        x,y,w,h=rect(e,(self.data['width'],self.data['height']),self._viewport,self.transform(*self._viewport));angle=finite(e.get('rotation',0));alpha=finite(e.get('opacity',1));scale=1.
        animations=self.animations_for(e)
        ends={}
        for a in animations:
            group=int(a.get('group',0));ends[group]=max(ends.get(group,0),float(a.get('delay',0))+float(a.get('duration',1)))
        offsets={};cycle=0.
        for group in sorted(ends):offsets[group]=cycle;cycle+=ends[group]
        own_timeline=e.get('animationMode','imported')!='imported' or str(e['id']) in self._manual_starts
        for a in animations:
            start=self.animation_start(e,a);duration=max(1e-6,float(a.get('duration',1)))
            if start is None and e.get('animationMode') in ('click','manual'):continue
            elapsed=self.time-start if start is not None else -1
            if e.get('animationMode')=='loop' and cycle>0 and str(e['id']) not in self._manual_starts:elapsed%=cycle
            if own_timeline:elapsed-=offsets.get(int(a.get('group',0)),0)
            t=-1 if start is None else elapsed-float(a.get('delay',0));p=max(0,min(1,t/duration));ex=bool(a.get('exit',False));kind=a['kind'];v=(1-p) if ex else p
            if kind in ('fade','appear'):alpha*=v if kind=='fade' else float(t>=0) if not ex else float(t<0)
            elif kind=='zoom':scale*=v
            elif kind=='fly':
                dx,dy=a.get('offset',(0,self.data['height']));x+=float(dx)*(p if ex else 1-p);y+=float(dy)*(p if ex else 1-p)
            elif kind=='spin':angle+=float(a.get('degrees',360))*p
            elif kind=='move':dx,dy=a.get('offset',(0,0));x+=float(dx)*p;y+=float(dy)*p
            if t<0 and kind in ('fade','appear','zoom','fly') and not ex:alpha=0
        x+=w*(1-scale)*.5;y+=h*(1-scale)*.5;w*=scale;h*=scale
        return x,y,w,h,angle,max(0,min(1,alpha))
    def render_items(self):
        if not self.enabled or self.active is None:return []
        incoming=[]
        for e in self.draw_elements():
            if e.get('enabled',True):incoming.extend(self.content.items(e,self.pose(e)))
        state=self._transition
        if state is None:return incoming
        settings=state['settings'];p=min(1,state['time']/settings['duration'])
        dx,dy={'left':(-self.data['width'],0),'right':(self.data['width'],0),'up':(0,-self.data['height']),'down':(0,self.data['height'])}[settings['direction']]
        def changed(items,old):
            result=[]
            for e,(x,y,w,h,angle,alpha) in items:
                if settings['kind']=='fade':alpha*=1-p if old else p
                else:x+=dx*(p if old else p-1);y+=dy*(p if old else p-1)
                result.append((e,(x,y,w,h,angle,alpha)))
            return result
        return changed(state['items'],True)+changed(incoming,False)
    def transform(self,width,height):
        from engine_ui_scaling import transform
        self._viewport=(width,height)
        return transform(self.data['width'],self.data['height'],width,height,self.scale_settings)
    def hit(self,px,py,width,height):
        if not self.enabled or self.active is None or self._transition is not None or self.loading:return None
        if width<=0 or height<=0:return None
        if not 0<=px<width or not 0<=py<height:return None
        sx,sy,ox,oy=self.transform(width,height);px=(px-ox)/sx;py=(py-oy)/sy
        from engine_ui_layout import anchored
        for e in reversed(self.slides[self.active]['elements']):
            if not anchored(e) and not (0<=px<self.data['width'] and 0<=py<self.data['height']):continue
            if not e.get('enabled',True) or not (e.get('onClick') or self.click_bindings(self.active,e['id']) or self.has_click_animation(e) or self.content.clickable(e)):continue
            x,y,w,h,angle,alpha=self.pose(e)
            if alpha<=.01:continue
            a=math.radians(-angle);dx=px-x-w*.5;dy=py-y-h*.5
            lx=math.cos(a)*dx-math.sin(a)*dy;ly=math.sin(a)*dx+math.cos(a)*dy
            if abs(lx)<=w*.5 and abs(ly)<=h*.5:return e
        return None
    def update(self,dt,pointer=None):
        if pointer:self.transform(pointer[3],pointer[4])
        self.content.update()
        if not self.enabled or self.active is None:self.last_down=False;self._pending_click=None;return False
        if self.assets:
            if self._pending_slide and self.assets_ready(self._pending_slide[0]):
                args=self._pending_slide;self._pending_slide=None;self.show_slide(*args)
            if self.loading:
                self.last_down=bool(pointer and pointer[2]);self.pressed_element=None;self._warming=True;return True
            if self._warming:
                dt=0.;self._warming=False
        if self._transition is not None:
            self._transition['time']+=max(0,float(dt))
            if self._transition['time']>=self._transition['settings']['duration']:self._transition=None
            self.last_down=bool(pointer and pointer[2]);self.pressed_element=None
            return True
        if not self._video_autoplay_done:
            self._video_autoplay_done=True
            for e in self.slides[self.active]['elements']:
                if e.get('enabled',True) and (e.get('video') or {}).get('autoplay') and e['video'].get('kind')=='file':
                    try:self.content.play_video(e['id'],self.active)
                    except Exception as ex:self.world.log('VIDEO: '+str(ex))
                    break
        self.time+=max(0,float(dt))
        if self._pending_click is not None:
            due,slide,element=self._pending_click
            if self.time>=due:
                self._pending_click=None
                if self.active==slide and element.get('enabled',True):self.dispatch_click(slide,element)
            self.last_down=bool(pointer and pointer[2]);self.pressed_element=None
            return True
        advance=self.slides[self.active].get('advanceAfter')
        if advance is not None and self.time>=float(advance):
            if self.next_slide():return True
        if pointer is None:return bool(self.slides[self.active].get('modal',False))
        x,y,down,width,height=pointer;hit=self.hit(x,y,width,height)
        if down and not self.last_down:self.pressed_element=hit
        if self.last_down and not down:
            if hit is not None and hit is self.pressed_element:
                self.click_animation(hit)
                slide=self.active
                if hit.get('waitForAnimation',False) and self.animation_length(hit)>0:
                    self._pending_click=(self.time+self.animation_length(hit),slide,hit)
                else:self.dispatch_click(slide,hit)
            elif self.pressed_element is None and 0<=x<width and 0<=y<height:
                if not self.advance_animation() and self.slides[self.active].get('advanceOnClick',False):self.next_slide()
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
            elif kind=='previous':self.previous_slide()
            elif kind=='animation':self.play_animation(a['id'],a.get('slide'))
            elif kind=='dialogueNext':self.dialogue_next(a['id'],a.get('slide'))
            elif kind=='dialogueReset':self.dialogue_reset(a['id'],a.get('slide'))
            elif kind=='text':self.set_text(a['id'],a['text'],a.get('slide'))
            elif kind=='videoPlay':self.play_video(a['id'],a.get('slide'))
            elif kind=='videoStop':self.stop_video()
            elif kind=='donate':
                from engine_transactions import for_world
                try:for_world(self.world).donate()
                except Exception as ex:self.world.log('DONATION: '+str(ex))
            elif kind=='quit':self.world.quit()
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
    def dialogue_next(self,element,slide=None):return self.content.next(element,slide)
    def dialogue_reset(self,element,slide=None):return self.content.reset(element,slide)
    def dialogue_finished(self,element,slide=None):return self.content.finished(element,slide)
    def set_text(self,element,text,slide=None):return self.content.set_text(element,text,slide)
    def play_video(self,element,slide=None):return self.content.play_video(element,slide)
    def stop_video(self):return self.content.stop_video()
    def draw(self):
        if not self.enabled or self.active is None:return
        if self.assets:self.assets.pump()
        if self.renderer is None:
            from engine_ui_gl import UIRenderer
            self.renderer=UIRenderer()
        self.renderer.draw(self)
