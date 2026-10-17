"""Mesa EGL pbuffer for real OpenGL tests on Linux, without a desktop/window."""
import ctypes as C


class EGLContext:
    def __init__(self,width=128,height=128):
        self.lib=C.CDLL('libEGL.so.1');self.display=None;self.surface=None;self.context=None
        def call(name,result,*types):
            f=getattr(self.lib,name);f.restype=result;f.argtypes=list(types);return f
        self.call=call;P=C.c_void_p;I=C.c_int
        address=call('eglGetProcAddress',P,C.c_char_p)(b'eglGetPlatformDisplayEXT')
        get=C.CFUNCTYPE(P,C.c_uint,P,P)(address)
        self.display=get(0x31DD,None,None)
        major,minor=I(),I()
        if not call('eglInitialize',I,P,P,P)(self.display,C.byref(major),C.byref(minor)):raise RuntimeError('No surfaceless EGL')
        if not call('eglBindAPI',I,C.c_uint)(0x30A2):raise RuntimeError('Cannot bind desktop OpenGL')
        attributes=(I*15)(0x3033,1,0x3040,8,0x3024,8,0x3023,8,0x3022,8,0x3021,8,0x3025,24,0x3038)
        config=P();count=I()
        if not call('eglChooseConfig',I,P,P,P,I,P)(self.display,attributes,C.byref(config),1,C.byref(count)) or not count.value:raise RuntimeError('No EGL config')
        attrs=(I*5)(0x3057,width,0x3056,height,0x3038)
        self.surface=call('eglCreatePbufferSurface',P,P,P,P)(self.display,config,attrs)
        self.context=call('eglCreateContext',P,P,P,P,P)(self.display,config,None,None)
        if not self.context or not self.surface or not call('eglMakeCurrent',I,P,P,P,P)(self.display,self.surface,self.surface,self.context):raise RuntimeError('No EGL context')
    def close(self):
        P=C.c_void_p;I=C.c_int
        if self.display:
            self.call('eglMakeCurrent',I,P,P,P,P)(self.display,None,None,None)
            if self.context:self.call('eglDestroyContext',I,P,P)(self.display,self.context)
            if self.surface:self.call('eglDestroySurface',I,P,P)(self.display,self.surface)
            self.call('eglTerminate',I,P)(self.display);self.display=None
