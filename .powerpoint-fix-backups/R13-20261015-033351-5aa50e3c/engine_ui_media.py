"""Asynchronous Windows embedded video host and explicit YouTube links."""
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
import json,math,os,re,shutil,subprocess,sys,tempfile,threading,time,webbrowser


def https_url(value):
    if not isinstance(value,str) or len(value)>4096 or any(ord(x)<32 for x in value):raise ValueError('Invalid URL')
    p=urlsplit(value)
    if p.scheme!='https' or not p.hostname or p.username or p.password:raise ValueError('Use an https:// URL without credentials')
    return value

def youtube_url(value):
    value=https_url(value);p=urlsplit(value);host=p.hostname.lower();parts=p.path.strip('/').split('/')
    if host in ('youtu.be','www.youtu.be'):video=parts[0]
    elif host in ('youtube.com','www.youtube.com','m.youtube.com','youtube-nocookie.com','www.youtube-nocookie.com'):
        video=parse_qs(p.query).get('v',[''])[0] if p.path=='/watch' else parts[1] if len(parts)>1 and parts[0] in ('embed','shorts','live','v') else ''
    else:raise ValueError('Use a YouTube video link')
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}',video):raise ValueError('Invalid YouTube video ID')
    return 'https://www.youtube.com/watch?v='+video

def open_url(url,log=lambda message:None):
    url=https_url(url)
    def work():
        try:
            if not webbrowser.open(url,new=2):log('Browser could not be opened.')
        except Exception as ex:log('BROWSER: '+str(ex))
    threading.Thread(target=work,name='ui-browser',daemon=True).start()

def video_settings(v):
    if not isinstance(v,dict) or v.get('kind') not in ('file','youtube'):raise ValueError('Video kind: file or youtube')
    out=dict(v);source=v.get('source','')
    if v['kind']=='youtube':out['source']=youtube_url(source)
    elif not isinstance(source,str) or not source or Path(source).is_absolute() or ':' in source or '\\' in source or '..' in Path(source).parts:raise ValueError('Video must use a path relative to the UI asset folder')
    volume=float(v.get('volume',1))
    if not math.isfinite(volume) or not 0<=volume<=1:raise ValueError('Video volume must be 0..1')
    if v.get('fit','fit') not in ('fit','fill','stretch'):raise ValueError('Video fit: fit/fill/stretch')
    out.update(volume=volume,loop=bool(v.get('loop',False)),autoplay=bool(v.get('autoplay',False)))
    return out


def atomic_control(path,data):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8');os.replace(tmp,path)


class VideoPlayer:
    """One active video per interface. All media decoding runs out of process."""
    def __init__(self,ui):
        self.ui=ui;self.process=None;self.folder=None;self.element=None;self.slide=None
        self.command={};self.last=None;self.next_poll=0.;self.started=0.;self.state='stopped';self.error=None;self.reapers=[]
    def play(self,sid,e):
        if getattr(self.ui.world,'editor_mode',False) or not getattr(self.ui.world,'scripts_allowed',True):return False
        v=video_settings(e['video'])
        if v['kind']=='youtube':open_url(v['source']);return True
        if self.process and self.element is e:
            if self.state=='ended':
                self.command['restart']=self.command.get('restart',0)+1;self.command['playing']=True
            else:self.command['playing']=not self.command['playing']
            self.last=None;return True
        if sys.platform!='win32':raise RuntimeError('Embedded video currently requires Windows. YouTube links work in the browser.')
        path=(self.ui.base/v['source']).resolve();path.relative_to(Path(self.ui.world.root).resolve())
        if not path.is_file():raise FileNotFoundError(path)
        if abs(float(e.get('rotation',0)))%360>.01:raise ValueError('Video element rotation must be 0 degrees')
        from engine_pptx_import import _powershell
        script=Path(__file__).with_name('tools')/'video_host.ps1'
        if not script.is_file():raise FileNotFoundError(script)
        library=script.parent.parent/'MyEngineVideo.dll'
        if not library.is_file():raise FileNotFoundError(library)
        self.stop();self.folder=Path(tempfile.mkdtemp(prefix='MyEngineVideo-'))
        self.slide=str(sid);self.element=e;self.started=time.monotonic();self.state='loading';self.error=None
        self.command={'parent':int(self.ui.world.core.hwnd),'source':str(path),'playing':True,'visible':False,'loop':v['loop'],'volume':v['volume'],'fit':v.get('fit','fit'),'rect':[0,0,1,1],'clip':[0,0,1,1]}
        control=self.folder/'control.json';atomic_control(control,self.command)
        env=os.environ.copy();env['MYENGINE_VIDEO_CONTROL']=str(control)
        try:
            with (self.folder/'host.log').open('wb') as log:
                self.process=subprocess.Popen([_powershell(),'-NoProfile','-NonInteractive','-STA','-ExecutionPolicy','Bypass','-File',str(script)],stdin=subprocess.DEVNULL,stdout=log,stderr=log,env=env,creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception:
            shutil.rmtree(self.folder,ignore_errors=True);self.folder=None;self.element=None;raise
        self.last=None;return True
    def update(self):
        if not self.process:return
        now=time.monotonic()
        if now<self.next_poll:return
        self.next_poll=now+.05
        if self.process.poll() is not None:
            detail=(self.folder/'host.log').read_text(encoding='utf-8',errors='replace')[-2000:]
            self.ui.world.log('VIDEO HOST CLOSED: '+detail);self.stop();return
        status=self.folder/'status.json'
        if status.exists():
            try:
                state=json.loads(status.read_text(encoding='utf-8-sig'));self.state=state.get('state','loading')
                if state.get('error') and state['error']!=self.error:
                    self.error=state['error'];self.ui.world.log('VIDEO: '+self.error)
            except (OSError,ValueError):pass
        elif now-self.started>30:
            self.ui.world.log('VIDEO: player did not start within 30 seconds');self.stop();return
        ui=self.ui;e=self.element
        visible=ui.enabled and ui.active==self.slide and e.get('enabled',True) and not ui.loading and not ui._transition
        width,height=getattr(ui,'_viewport',(0,0))
        if visible and width and height:
            x,y,w,h,angle,alpha=ui.pose(e);sx,sy,ox,oy=ui.transform(width,height)
            x=round(ox+x*sx);y=round(oy+y*sy);w=max(1,round(w*sx));h=max(1,round(h*sy))
            self.command['rect']=[x,y,w,h];self.command['clip']=[max(0,-x),max(0,-y),max(0,min(w,width-x)),max(0,min(h,height-y))]
            visible=alpha>.99 and abs(angle)%360<.01 and x<width and y<height and x+w>0 and y+h>0
        else:visible=False
        if ui.active!=self.slide or not ui.enabled or not e.get('enabled',True):self.stop();return
        self.command['visible']=bool(visible)
        if self.command!=self.last:
            atomic_control(self.folder/'control.json',self.command);self.last=dict(self.command)
    def stop(self):
        process,folder=self.process,self.folder;self.process=None;self.folder=None;self.element=None;self.state='stopped'
        if process:
            try:atomic_control(folder/'control.json',{'close':True})
            except OSError:pass
            def reap():
                try:process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:process.wait(timeout=2)
                    except subprocess.TimeoutExpired:process.kill();process.wait()
                finally:shutil.rmtree(folder,ignore_errors=True)
            # Never wait for the media process on the engine's render thread.
            t=threading.Thread(target=reap,name='video-cleanup',daemon=True);t.start()
    def close(self):self.stop()
