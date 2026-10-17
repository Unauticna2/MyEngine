"""Linux x86_64 SDL2 player. Same Python world, GLSL renderer and MASM physics."""
import ctypes as C,ctypes.util,math,os,threading,time,sys,json
from pathlib import Path
from engine_gl import GL,F,I,U,P
from engine_runtime import Vec3,World,switch_scene

class LinuxCore:
    physics_prefix='Bridge'
    def __init__(self,root,window=True):
        self.root=Path(root).resolve();native=self.root/'platforms/linux'
        self.dll=C.CDLL(str(native/'libMyEnginePhysics.so'))
        os.environ.setdefault('MYENGINE_SLICE_DLL',str(native/'libSlice4D.so'))
        self.owner_thread=threading.get_ident();self.camera=(F*6)(0,2,7,12,0,0);self.light=Vec3();self.camera_control=U(1);self.runtime_flags=U(9);self.render_flags=U(1);self.keys=bytearray(256);self.scene=None;self.running=True;self.window=None;self.context=None;self.sdl=None;self.mouse=(0,0,False,1280,720);self.size=(1280,720);self.title='MyEngine 2'
        if window:self.open_window()
        self.gl=GL()
    def sf(self,name,result,*args):
        f=getattr(self.sdl,name);f.restype=result;f.argtypes=list(args);return f
    def open_window(self):
        path=C.util.find_library('SDL2-2.0') or 'libSDL2-2.0.so.0';self.sdl=C.CDLL(path)
        if self.sf('SDL_Init',I,U)(0x20):raise RuntimeError(self.error())
        try:
            for key,value in ((5,1),(6,24),(17,2),(18,1)):
                if self.sf('SDL_GL_SetAttribute',I,I,I)(key,value):raise RuntimeError(self.error())
            self.window=self.sf('SDL_CreateWindow',P,C.c_char_p,I,I,I,I,U)(b'MyEngine 2',0x2FFF0000,0x2FFF0000,*self.size,0x26)
            if not self.window:raise RuntimeError(self.error())
            self.context=self.sf('SDL_GL_CreateContext',P,P)(self.window)
            if not self.context:raise RuntimeError(self.error())
            self.sf('SDL_GL_SetSwapInterval',I,I)(1)
        except BaseException:self.close();raise
    def error(self):return self.sf('SDL_GetError',C.c_char_p)().decode(errors='replace')
    def assert_thread(self):
        if threading.get_ident()!=self.owner_thread:raise RuntimeError('Use the render owner thread')
    def create_mesh(self,mesh):
        self.assert_thread();f=self.gl.fn;lid=f('glGenLists',U,I)(1)
        if not lid:raise RuntimeError('Mesh allocation failed')
        f('glNewList',None,U,U)(lid,0x1300);f('glBegin',None,U)(4)
        for o in range(0,len(mesh.vertices),8):
            v=mesh.vertices[o:o+8];f('glNormal3f',None,F,F,F)(*v[3:6]);f('glTexCoord2f',None,F,F)(*v[6:]);f('glVertex3f',None,F,F,F)(*v[:3])
        f('glEnd',None)();f('glEndList',None)();return lid
    def create_texture(self,image):
        self.assert_thread();w,h,pixels=image;f=self.gl.fn;t=U();f('glGenTextures',None,I,P)(1,C.byref(t));f('glBindTexture',None,U,U)(0x0DE1,t.value)
        for k,v in ((0x2801,0x2601),(0x2800,0x2601),(0x2802,0x812F),(0x2803,0x812F)):f('glTexParameteri',None,U,U,I)(0x0DE1,k,v)
        raw=C.create_string_buffer(pixels);f('glTexImage2D',None,U,I,I,I,I,I,U,U,P)(0x0DE1,0,0x8058,w,h,0,0x1908,0x1401,raw)
        return t.value
    def delete_mesh(self,id):self.gl.fn('glDeleteLists',None,U,I)(id,1)
    def delete_texture(self,id):self.gl.fn('glDeleteTextures',None,I,P)(1,C.byref(U(id)))
    def submit(self,entities):self.scene=entities
    def clear(self):self.scene=None
    def set_title(self,text):
        self.title=text
        if self.window:self.sf('SDL_SetWindowTitle',None,P,C.c_char_p)(self.window,text.encode('utf-8'))
    def pointer(self):return self.mouse
    def request_quit(self):self.running=False
    def events(self,dt):
        event=(C.c_ubyte*56)()
        while self.sf('SDL_PollEvent',I,P)(event):
            if U.from_buffer(event).value==0x100:self.running=False
        count=I();raw=self.sf('SDL_GetKeyboardState',C.POINTER(C.c_ubyte),P)(C.byref(count))
        previous=self.keys[:];self.keys[:]=bytes(256)
        # SDL scancodes -> the same virtual-key API as the Windows engine.
        pairs=[(4+i,65+i) for i in range(26)]+[(30+i,49+i) for i in range(9)]+[(39,48)]+[(58+i,112+i) for i in range(12)]+[(40,13),(41,27),(43,9),(44,32),(79,39),(80,37),(81,40),(82,38),(224,17),(228,17),(225,16),(229,16),(226,18),(230,18)]
        focused=bool(self.sf('SDL_GetWindowFlags',U,P)(self.window)&0x200)
        if focused:
            for scan,key in pairs:self.keys[key]|=raw[scan]
        x=I();y=I();buttons=self.sf('SDL_GetMouseState',U,P,P)(C.byref(x),C.byref(y));dx=I();dy=I();self.sf('SDL_GetRelativeMouseState',U,P,P)(C.byref(dx),C.byref(dy))
        width=I();height=I();self.sf('SDL_GetWindowSize',None,P,P,P)(self.window,C.byref(width),C.byref(height));self.size=(max(1,width.value),max(1,height.value));self.mouse=(x.value,y.value,focused and bool(buttons&1),*self.size)
        flags=self.runtime_flags.value
        if focused and buttons&4 and flags&1:self.camera[4]=(self.camera[4]+dx.value*.15)%360;self.camera[3]=max(-89,min(89,self.camera[3]+dy.value*.15))
        if flags&4 and self.keys[27]:self.running=False
        if flags&2 and self.keys[82] and not previous[82]:self.camera[:]=(0,2,7,12,0,0)
        if flags&8 and self.camera_control.value:
            speed=5*dt*(3 if self.keys[16] else 1);forward=self.keys[87]-self.keys[83];side=self.keys[68]-self.keys[65];yaw=math.radians(self.camera[4])
            self.camera[0]+=(math.sin(yaw)*forward+math.cos(yaw)*side)*speed
            self.camera[2]+=(-math.cos(yaw)*forward+math.sin(yaw)*side)*speed
            self.camera[1]+=(self.keys[32]-self.keys[17])*speed
    def begin_frame(self):
        f=self.gl.fn;w,h=self.size;f('glViewport',None,I,I,I,I)(0,0,w,h);f('glClearColor',None,F,F,F,F)(0,0,0,1);f('glClear',None,U)(0x4100);f('glEnable',None,U)(0x0B71)
        f('glMatrixMode',None,U)(0x1701);f('glLoadIdentity',None)();f('glFrustum',None,*([C.c_double]*6))(-.057735*w/h,.057735*w/h,-.057735,.057735,.1,1000.)
        f('glMatrixMode',None,U)(0x1700);f('glLoadIdentity',None)();f('glRotatef',None,F,F,F,F)(self.camera[3],1,0,0);f('glRotatef',None,F,F,F,F)(self.camera[4],0,1,0);f('glTranslatef',None,F,F,F)(*[-v for v in self.camera[:3]])
    def close(self):
        if self.sdl:
            if self.context:self.sf('SDL_GL_DeleteContext',None,P)(self.context);self.context=None
            if self.window:self.sf('SDL_DestroyWindow',None,P)(self.window);self.window=None
            self.sf('SDL_Quit',None)()

def run(root,scene):
    import engine_runtime
    core=LinuxCore(Path(__file__).parent);world=None
    try:
        root=Path(root).resolve();os.chdir(root)
        if str(root) not in sys.path:sys.path.insert(1,str(root))
        world=World(core,root);engine_runtime._world=world;world.load(scene);last=time.perf_counter()
        while core.running:
            now=time.perf_counter();dt=min(.05,now-last);last=now;core.events(dt);world.tick(dt,core.keys)
            world=engine_runtime.finish_frame(world);engine_runtime._world=world
            if not core.running:break
            core.begin_frame();world.draw();core.sf('SDL_GL_SwapWindow',None,P)(core.window)
    finally:
        if world:world.shutdown()
        engine_runtime._world=None;core.close()

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--project',default=str(Path(__file__).parent));p.add_argument('--scene',default='map.json');a=p.parse_args();run(a.project,a.scene)
