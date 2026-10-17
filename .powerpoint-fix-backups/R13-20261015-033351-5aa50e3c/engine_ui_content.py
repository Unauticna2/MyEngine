"""Dialogue and mutable-text components attached to imported UI element IDs."""
import hashlib,json,math
from engine_ui_text import style,TextTextures
from engine_ui_layout import sub_pose


def dialogue(value):
    if value is None:return None
    if not isinstance(value,dict):raise ValueError('Dialogue must be an object')
    lines=value.get('lines',[])
    if not isinstance(lines,list) or not 1<=len(lines)<=1000 or any(not isinstance(x,str) or len(x)>4096 or '\0' in x for x in lines):
        raise ValueError('Dialogue: 1..1000 text entries, up to 4096 characters each')
    return {'lines':list(lines),'clickToAdvance':bool(value.get('clickToAdvance',True)),'loop':bool(value.get('loop',False))}


def validate_content(e):
    from engine_ui_layout import anchors
    anchors(e.get('anchors'));dialogue(e.get('dialogue'));style(e.get('textStyle') or e.get('textSlot',{}).get('style'))
    slot=e.get('textSlot')
    if slot:
        r=slot.get('rect')
        if not isinstance(r,list) or len(r)!=4 or any(not math.isfinite(float(x)) for x in r) or min(r[2:])<=0:raise ValueError('Invalid text rectangle')
    if 'text' in e and (not isinstance(e['text'],str) or len(e['text'])>4096 or '\0' in e['text']):raise ValueError('Text must be a string of at most 4096 characters')
    if e.get('video'):
        from engine_ui_media import video_settings
        video_settings(e['video'])


def media_paths(data):
    for s in data['slides']:
        for e in s.get('elements',[]):
            v=e.get('video') or {}
            if v.get('kind')=='file' and v.get('source'):yield v['source']


class UIContent:
    def __init__(self,ui):
        self.ui=ui;self.state={};self.textures=None;self.media=None
    def element(self,element,slide=None):
        sid=str(slide if slide is not None else self.ui.active)
        return sid,next(e for e in self.ui.slides[sid]['elements'] if str(e['id'])==str(element))
    def component(self,sid,e):return self.state.setdefault((sid,str(e['id'])),{'index':0,'finished':False})
    def next(self,element,slide=None):
        sid,e=self.element(element,slide);d=dialogue(e.get('dialogue'))
        if not d:return False
        state=self.component(sid,e)
        if state['index']+1<len(d['lines']):state['index']+=1;state['finished']=False
        elif d['loop']:state['index']=0;state['finished']=False
        else:
            if state['finished']:return False
            state['finished']=True
            if sid==self.ui.active:self.ui.actions(e.get('onDialogueEnd',[]))
        state.pop('text',None)
        return True
    def reset(self,element,slide=None):
        sid,e=self.element(element,slide);self.state.pop((sid,str(e['id'])),None)
    def finished(self,element,slide=None):
        sid,e=self.element(element,slide);return self.component(sid,e)['finished']
    def set_text(self,element,text,slide=None):
        if not isinstance(text,str) or len(text)>4096 or '\0' in text:raise ValueError('Text limit: 4096 characters')
        sid,e=self.element(element,slide);self.component(sid,e)['text']=text
    def dynamic(self,e,sid=None):
        sid=self.ui.active if sid is None else str(sid)
        return e.get('dialogue') is not None or 'text' in e or 'text' in self.state.get((sid,str(e['id'])),{})
    def text(self,e,sid=None):
        sid=self.ui.active if sid is None else str(sid);s=self.component(sid,e)
        if 'text' in s:return s['text']
        if e.get('dialogue'):return e['dialogue']['lines'][s['index']]
        return e.get('text','')
    def clickable(self,e):return bool(e.get('video') or (e.get('dialogue') or {}).get('clickToAdvance',True) and e.get('dialogue'))
    def click(self,sid,e):
        if e.get('dialogue') and e['dialogue'].get('clickToAdvance',True):self.next(e['id'],sid)
        elif e.get('video'):self.play_video(e['id'],sid)
    def items(self,e,pose):
        if not self.dynamic(e):return [(e,pose)]
        slot=e.get('textSlot') or {};base=dict(e)
        if slot.get('image'):base['image']=slot['image'];base['frames']=[]
        elif not base.get('image'):base.setdefault('color',[0,0,0,.8])
        settings=style(e.get('textStyle') or slot.get('style'))
        r=slot.get('rect',[8,8,max(1,e['rect'][2]-16),max(1,e['rect'][3]-16)])
        text=self.text(e);text_pose=sub_pose(pose,r,e['rect'][2:]);tw,th=text_pose[2:4]
        if tw<=0 or th<=0:return [(base,pose)]
        # Rasterize at current element proportions; anchors may stretch the box.
        settings['size']*=min(pose[2]/e['rect'][2],pose[3]/e['rect'][3]);settings['size']=max(4,min(200,settings['size']))
        key=hashlib.sha256(json.dumps([text,round(tw,2),round(th,2),settings],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        if self.textures is None:self.textures=TextTextures(self.ui.world)
        self.textures.request(key,(text,tw,th,settings))
        item={'id':'_text_'+str(e['id']),'_textKey':key,'rect':[0,0,tw,th],'color':[1,1,1,1],'anchors':e.get('anchors')}
        return [(base,pose),(item,text_pose)]
    def play_video(self,element,slide=None):
        sid,e=self.element(element,slide)
        if not e.get('video'):raise ValueError('This UI element has no video')
        if self.media is None:
            from engine_ui_media import VideoPlayer
            self.media=VideoPlayer(self.ui)
        return self.media.play(sid,e)
    def stop_video(self):
        if self.media:self.media.stop()
    def update(self):
        if self.media:self.media.update()
    def close(self):
        if self.textures:self.textures.close()
        if self.media:self.media.close()
