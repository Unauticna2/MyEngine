"""Viewport transform handles. CPU hit testing; changes stay on the ECS owner thread."""
import ctypes as C
import math
from engine_gl import GL,I,U,F,P,multiply,inverse
from engine_collision import rotation_axes

COLORS=((1,.22,.2),(.3,1,.35),(.3,.6,1),(1,.3,1))
AXES=((1,0,0),(0,1,0),(0,0,1))
def dot(a,b):return sum(x*y for x,y in zip(a,b))
def add(a,b):return tuple(x+y for x,y in zip(a,b))
def sub(a,b):return tuple(x-y for x,y in zip(a,b))
def mul(a,s):return tuple(x*s for x in a)
def cross(a,b):return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
def unit(a):return mul(a,1/max(1e-12,math.sqrt(dot(a,a))))
def transform(m,p):return tuple(sum(m[c*4+r]*p[c] for c in range(4)) for r in range(4))
def project(m,p,width,height):
    q=transform(m,(*p,1))
    if q[3]<=.001:return None
    return ((q[0]/q[3]*.5+.5)*width,(.5-q[1]/q[3]*.5)*height)
def segment_distance(p,a,b):
    d=sub(b,a);t=max(0,min(1,dot(sub(p,a),d)/max(1e-9,dot(d,d))))
    q=sub(p,add(a,mul(d,t)));return math.sqrt(dot(q,q))
def ray_plane(inv_vp,mouse,width,height,center,normal):
    x=mouse[0]/width*2-1;y=1-mouse[1]/height*2
    a=transform(inv_vp,(x,y,-1,1));b=transform(inv_vp,(x,y,1,1))
    a=tuple(v/a[3] for v in a[:3]);b=tuple(v/b[3] for v in b[:3]);d=sub(b,a)
    denom=dot(d,normal)
    if abs(denom)<1e-8:return None
    return sub(add(a,mul(d,dot(sub(center,a),normal)/denom)),center)
def snapshot(e):
    return {'positions':dict(zip('xyzw',(*e.position,e.w))),
            'rotations':dict(zip('xyz',e.rotation)),
            'scales':dict(zip('xyzw',(*e.scale,e.scale_w))),
            'rotations4D':dict(zip(('xw','yw','zw'),e.rotation4))}
def restore(e,d):
    e.position=d['positions'];e.w=d['positions']['w'];e.rotation=d['rotations'];e.scale=d['scales']
    e.scale_w=d['scales']['w'];e.rotation4.set(*(d['rotations4D'][k] for k in ('xw','yw','zw')))


class WinMouse:
    class Point(C.Structure):_fields_=[('x',C.c_int32),('y',C.c_int32)]
    def __init__(self,core):
        self.user=core.user;self.hwnd=core.hwnd
        specs={'GetCursorPos':([P],I),'ScreenToClient':([P,P],I),
               'GetAsyncKeyState':([I],C.c_short),'WindowFromPoint':([self.Point],P)}
        for name,(args,result) in specs.items():
            f=getattr(self.user,name);f.argtypes=args;f.restype=result
    def poll(self):
        p=self.Point()
        if not self.user.GetCursorPos(C.byref(p)):return (0,0),False,False,False
        over=self.user.WindowFromPoint(p)==self.hwnd
        self.user.ScreenToClient(self.hwnd,C.byref(p))
        return (p.x,p.y),bool(self.user.GetAsyncKeyState(1)&0x8000),over,bool(self.user.GetAsyncKeyState(17)&0x8000)


class Gizmo:
    def __init__(self,editor,core,mouse=None):
        self.editor=editor;self.mode='move';self.gl=None;self.mouse=mouse or WinMouse(core)
        self.drag=None;self.was_down=False
    def cancel(self):
        if self.drag:
            e=self.drag['entity']
            if not e.destroyed:restore(e,self.drag['before'])
            e.world.core.camera_control.value=self.drag['camera_control']
            self.drag=None;self.editor.channel.send({'type':'gizmo_cancel'})
    def layout(self,e,vp,view,projection,width,height):
        center=project(vp,tuple(e.position),width,height)
        if center is None:return []
        eye=transform(view,(*e.position,1));length=max(.01,abs(eye[2])*2/max(.01,projection[5])/height*90)
        handles=[];axes=AXES
        if self.mode=='scale':axes=rotation_axes(tuple(e.rotation))
        elif self.mode=='rotate':
            z=math.radians(e.rotation.z)
            axes=(rotation_axes(tuple(e.rotation))[0],(-math.sin(z),math.cos(z),0),(0,0,1))
        if self.mode in ('move','scale'):
            for axis,direction in enumerate(axes):
                end=project(vp,add(tuple(e.position),mul(direction,length)),width,height)
                if end is not None and dot(sub(end,center),sub(end,center))>25:
                    handles.append({'axis':axis,'points':[center,end],'length':length,'center':center})
            if e.is_4d:
                handles.append({'axis':3,'points':[center,(center[0]-68,center[1]-68)],'length':max(e.layer_spacing,abs(e.layer_spacing*e.scale_w)*10),'center':center})
        elif self.mode=='rotate':
            for axis,normal in enumerate(axes):
                u=unit(cross(normal,(0,1,0) if abs(normal[1])<.8 else (1,0,0)));v=cross(normal,u)
                ring=[]
                for i in range(65):
                    angle=i*2*math.pi/64
                    q=add(tuple(e.position),mul(add(mul(u,math.cos(angle)),mul(v,math.sin(angle))),length))
                    p=project(vp,q,width,height)
                    if p is None:ring=[];break
                    ring.append(p)
                if ring:handles.append({'axis':axis,'points':ring,'normal':normal,'center':center})
        elif self.mode=='rotate4' and e.is_4d:
            for axis in range(3):
                radius=48+axis*22
                ring=[(center[0]+math.cos(i*math.pi/32)*radius,center[1]+math.sin(i*math.pi/32)*radius) for i in range(65)]
                handles.append({'axis':axis,'points':ring,'center':center})
        return handles
    def begin(self,e,handle,mouse,inv_vp,width,height):
        self.drag={'entity':e,'before':snapshot(e),'handle':handle,'mouse':mouse,'mode':self.mode,
                   'inv':inv_vp,'width':width,'height':height,'angle':None,'unwrapped':0,
                   'camera_control':e.world.core.camera_control.value}
        e.world.core.camera_control.value=0
        if self.mode=='rotate':self.drag['start_vector']=ray_plane(inv_vp,mouse,width,height,tuple(e.position),handle['normal'])
        if self.mode=='rotate4':self.drag['angle']=math.atan2(mouse[1]-handle['center'][1],mouse[0]-handle['center'][0])
        self.editor.channel.send({'type':'gizmo_begin','name':e.name})
    def motion(self,mouse,snap=False):
        d=self.drag;e=d['entity'];h=d['handle'];axis=h['axis'];before=d['before'];mode=d['mode']
        if e.destroyed:self.cancel();return
        if mode in ('move','scale'):
            direction=sub(h['points'][-1],h['points'][0]);amount=dot(sub(mouse,d['mouse']),direction)/max(1,dot(direction,direction))
            key='xyzw'[axis]
            if mode=='move':
                value=before['positions'][key]+amount*h['length']
                if snap:value=round(value/.1)*.1
                if axis==3:e.w=value
                else:p=list(e.position);p[axis]=value;e.position=p
            else:
                value=before['scales'][key]*max(.01,1+amount)
                if snap:value=round(value/.1)*.1
                if abs(value)<.0001:value=.0001 if value>=0 else -.0001
                if axis==3:e.scale_w=value
                else:s=list(e.scale);s[axis]=value;e.scale=s
        else:
            if mode=='rotate':
                current=ray_plane(d['inv'],mouse,d['width'],d['height'],tuple(e.position),h['normal'])
                start=d.get('start_vector')
                if current and start and dot(start,start)>1e-8 and dot(current,current)>1e-8:
                    angle=math.atan2(dot(h['normal'],cross(start,current)),dot(start,current))
                else:angle=math.radians((mouse[0]-d['mouse'][0])*.7-(mouse[1]-d['mouse'][1])*.7)
            else:angle=math.atan2(mouse[1]-h['center'][1],mouse[0]-h['center'][0])
            if d['angle'] is None:d['angle']=0
            step=(angle-d['angle']+math.pi)%(2*math.pi)-math.pi;d['unwrapped']+=step;d['angle']=angle
            degrees=math.degrees(d['unwrapped'])
            if snap:degrees=round(degrees/15)*15
            if mode=='rotate':
                r=list(e.rotation);r[axis]=before['rotations']['xyz'[axis]]+degrees;e.rotation=r
            else:
                r=list(e.rotation4);r[axis]=before['rotations4D'][('xw','yw','zw')[axis]]+degrees;e.rotation4.set(*r)
    def finish(self):
        if not self.drag:return
        e=self.drag['entity'];before=self.drag['before'];e.world.core.camera_control.value=self.drag['camera_control'];self.drag=None
        if not e.destroyed:self.editor.channel.send({'type':'gizmo_commit','name':e.name,'transform':snapshot(e),'changed':before!=snapshot(e)})
    def frame(self,world):
        if self.gl is None:self.gl=GL()
        e=world.find(self.editor.selected) if self.editor.selected else None
        mouse,down,over,snap=self.mouse.poll()
        if not world.editor_mode or e is None or e.is_player or self.mode=='none':
            self.cancel();self.was_down=down;return
        gl=self.gl;view=(F*16)();projection=(F*16)();viewport=(I*4)()
        gl.fn('glGetFloatv',None,U,P)(0x0BA6,view);gl.fn('glGetFloatv',None,U,P)(0x0BA7,projection)
        gl.fn('glGetIntegerv',None,U,P)(0x0BA2,viewport);width,height=viewport[2:4]
        if width<1 or height<1:return
        vp=multiply(projection,view);handles=self.layout(e,vp,view,projection,width,height)
        if down and not self.was_down and over:
            candidates=[(min(segment_distance(mouse,a,b) for a,b in zip(h['points'],h['points'][1:])),h) for h in handles]
            if candidates:
                distance,handle=min(candidates,key=lambda pair:pair[0])
                if distance<9:self.begin(e,handle,mouse,inverse(vp),width,height)
        if self.drag:
            if down:self.motion(mouse,snap)
            else:self.finish()
        self.was_down=down
        self.draw(handles,width,height)
    def draw(self,handles,width,height):
        gl=self.gl;gl.fn('glPushAttrib',None,U)(0xfffff)
        gl.fn('glMatrixMode',None,U)(0x1701);gl.fn('glPushMatrix',None)();gl.fn('glLoadIdentity',None)()
        gl.fn('glMatrixMode',None,U)(0x1700);gl.fn('glPushMatrix',None)();gl.fn('glLoadIdentity',None)()
        def vertex(p):gl.fn('glVertex2f',None,F,F)(p[0]/width*2-1,1-p[1]/height*2)
        try:
            for cap in (0x0B50,0x0DE1,0x0B71,0x0BC0):gl.fn('glDisable',None,U)(cap)
            gl.fn('glDepthMask',None,C.c_ubyte)(0);gl.fn('glLineWidth',None,F)(3)
            for h in handles:
                color=(1,1,.4) if self.drag and self.drag['handle']['axis']==h['axis'] else COLORS[h['axis']]
                gl.fn('glColor3f',None,F,F,F)(*color);gl.fn('glBegin',None,U)(3)
                for p in h['points']:vertex(p)
                gl.fn('glEnd',None)()
                if len(h['points'])==2:
                    a,b=h['points'];d=unit(sub(b,a));side=(-d[1],d[0])
                    if self.mode=='move':points=[add(sub(b,mul(d,12)),mul(side,5)),b,sub(sub(b,mul(d,12)),mul(side,5))]
                    else:points=[(b[0]-5,b[1]-5),(b[0]+5,b[1]-5),(b[0]+5,b[1]+5),(b[0]-5,b[1]+5),(b[0]-5,b[1]-5)]
                    gl.fn('glBegin',None,U)(3)
                    for p in points:vertex(p)
                    gl.fn('glEnd',None)()
        finally:
            gl.fn('glPopMatrix',None)();gl.fn('glMatrixMode',None,U)(0x1701);gl.fn('glPopMatrix',None)()
            gl.fn('glMatrixMode',None,U)(0x1700);gl.fn('glPopAttrib',None)()
