"""Small OpenGL loader. Must be constructed on the thread owning the GL context."""
import ctypes as C
import sys

P=C.c_void_p; I=C.c_int; U=C.c_uint; F=C.c_float

class GL:
    def __init__(self):
        if sys.platform == 'win32':
            self.lib=C.WinDLL('opengl32.dll')
            self.lib.wglGetProcAddress.argtypes=[C.c_char_p]
            self.lib.wglGetProcAddress.restype=P
            self.address=self.lib.wglGetProcAddress
            self.proto=C.WINFUNCTYPE
        else: # Also permits real headless Mesa validation of the shipped shaders.
            self.lib=C.CDLL('libGL.so.1'); self.address=None; self.proto=C.CFUNCTYPE
        self.cache={}

    def fn(self, name, result, *args):
        if name in self.cache: return self.cache[name]
        try: f=getattr(self.lib,name); f.restype=result; f.argtypes=list(args)
        except AttributeError:
            address=self.address(name.encode('ascii'))
            if address in (None,0,1,2,3,C.c_void_p(-1).value):
                raise RuntimeError(f'{name} unavailable. Voxel rendering requires OpenGL 2.1 or newer.')
            f=self.proto(result,*args)(address)
        self.cache[name]=f; return f

    def compile(self, vertex, fragment):
        shaders=[]; program=0
        try:
            for kind,source in ((0x8B31,vertex),(0x8B30,fragment)):
                shader=self.fn('glCreateShader',U,U)(kind); shaders.append(shader)
                src=C.c_char_p(source.encode('utf-8'))
                self.fn('glShaderSource',None,U,I,P,P)(shader,1,C.byref(src),None)
                self.fn('glCompileShader',None,U)(shader)
                ok=I(); self.fn('glGetShaderiv',None,U,U,P)(shader,0x8B81,C.byref(ok))
                if not ok.value:
                    log=C.create_string_buffer(8192)
                    self.fn('glGetShaderInfoLog',None,U,I,P,P)(shader,len(log),None,log)
                    raise RuntimeError('Voxel shader: '+log.value.decode(errors='replace'))
            program=self.fn('glCreateProgram',U)()
            for shader in shaders: self.fn('glAttachShader',None,U,U)(program,shader)
            self.fn('glLinkProgram',None,U)(program)
            ok=I(); self.fn('glGetProgramiv',None,U,U,P)(program,0x8B82,C.byref(ok))
            if not ok.value:
                log=C.create_string_buffer(8192)
                self.fn('glGetProgramInfoLog',None,U,I,P,P)(program,len(log),None,log)
                raise RuntimeError('Voxel program: '+log.value.decode(errors='replace'))
            return program
        except Exception:
            if program:self.fn('glDeleteProgram',None,U)(program)
            raise
        finally:
            for shader in shaders:self.fn('glDeleteShader',None,U)(shader)


def multiply(a,b):
    return [sum(a[k*4+r]*b[c*4+k] for k in range(4)) for c in range(4) for r in range(4)]

def inverse(a):
    m=[[a[c*4+r] for c in range(4)]+[float(r==c) for c in range(4)] for r in range(4)]
    for i in range(4):
        j=max(range(i,4), key=lambda r:abs(m[r][i]))
        if abs(m[j][i])<1e-14: raise ValueError('Singular transform')
        m[i],m[j]=m[j],m[i]; d=m[i][i]; m[i]=[x/d for x in m[i]]
        for r in range(4):
            if r!=i:
                d=m[r][i]; m[r]=[x-d*y for x,y in zip(m[r],m[i])]
    return [m[r][c+4] for c in range(4) for r in range(4)]

def model_matrix(position, rotation, scale):
    from engine_collision import rotation_axes
    axes=rotation_axes(rotation)
    return [v for i in range(3) for v in (*[x*scale[i] for x in axes[i]],0)] + [*position,1]


_selection_gl=None
def draw_selection(entity,color=(1,.65,.12),width=2):
    """Editor-only world-space bounding outline; leaves all rendering state intact."""
    global _selection_gl
    if entity.destroyed or not entity.active:return
    if _selection_gl is None:_selection_gl=GL()
    gl=_selection_gl;previous=I()
    # Fixed-function drawing also works when an older driver has no shader support.
    programmable=True
    try:use=gl.fn('glUseProgram',None,U)
    except RuntimeError:programmable=False
    if programmable:gl.fn('glGetIntegerv',None,U,P)(0x8B8D,C.byref(previous));use(0)
    if entity.voxels:
        g=entity.voxels.grid;lo=tuple(-n*g.cell_size*.5 for n in g.size);hi=tuple(-x for x in lo)
    elif entity.layers and entity.layer is not None:
        lo=entity.layers[entity.layer].minimum;hi=entity.layers[entity.layer].maximum
    else:lo=(-.5,-.5,-.5);hi=(.5,.5,.5)
    gl.fn('glPushAttrib',None,U)(0xfffff);gl.fn('glPushMatrix',None)()
    try:
        for cap in (0x0B50,0x0DE1,0x0BC0):gl.fn('glDisable',None,U)(cap)
        gl.fn('glDepthMask',None,C.c_ubyte)(0);gl.fn('glLineWidth',None,F)(width)
        m=(F*16)(*model_matrix(tuple(entity.position),tuple(entity.rotation),tuple(entity.scale)))
        gl.fn('glMultMatrixf',None,P)(m);gl.fn('glColor3f',None,F,F,F)(*color)
        vertices=[(hi[0] if i&1 else lo[0],hi[1] if i&2 else lo[1],hi[2] if i&4 else lo[2]) for i in range(8)]
        gl.fn('glBegin',None,U)(1)
        for i in range(8):
            for bit in (1,2,4):
                if not i&bit:
                    gl.fn('glVertex3f',None,F,F,F)(*vertices[i]);gl.fn('glVertex3f',None,F,F,F)(*vertices[i|bit])
        gl.fn('glEnd',None)()
    finally:
        gl.fn('glPopMatrix',None)();gl.fn('glPopAttrib',None)()
        if programmable:use(previous.value)
