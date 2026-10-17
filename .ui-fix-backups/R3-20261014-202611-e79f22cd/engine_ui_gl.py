"""Alpha-blended UI sprites over the game framebuffer, with letterboxed coordinates."""
import ctypes as C,math
from engine_gl import GL,I,U,F,P
class UIRenderer:
    def __init__(self,gl=None):self.gl=gl or GL()
    def draw(self,ui):
        gl=self.gl;f=gl.fn;viewport=(I*4)();previous=I()
        f('glGetIntegerv',None,U,P)(0x0BA2,viewport);f('glGetIntegerv',None,U,P)(0x8B8D,C.byref(previous));width,height=viewport[2:4]
        if not width or not height:return
        scale,ox,oy=ui.transform(width,height)
        f('glPushAttrib',None,U)(0xfffff);f('glUseProgram',None,U)(0)
        f('glMatrixMode',None,U)(0x1701);f('glPushMatrix',None)();f('glLoadIdentity',None)()
        f('glOrtho',None,*([C.c_double]*6))(0,width,height,0,-1,1)
        f('glMatrixMode',None,U)(0x1700);f('glPushMatrix',None)();f('glLoadIdentity',None)()
        try:
            for cap in (0x0B71,0x0B50,0x0B44,0x0BC0,0x0C11):f('glDisable',None,U)(cap)
            f('glDepthMask',None,C.c_ubyte)(0);f('glEnable',None,U)(0x0BE2);f('glBlendFunc',None,U,U)(0x0302,0x0303)
            for unit in range(8):f('glActiveTexture',None,U)(0x84C0+unit);f('glDisable',None,U)(0x0DE1);f('glDisable',None,U)(0x806F)
            f('glActiveTexture',None,U)(0x84C0)
            slide=ui.slides[ui.active];elements=slide['elements']
            if slide.get('background'):elements=[{'id':'_background','image':slide['background'],'rect':[0,0,ui.data['width'],ui.data['height']]},*elements]
            for e in elements:
                if not e.get('enabled',True):continue
                x,y,w,h,angle,alpha=ui.pose(e)
                if alpha<=0 or w<=0 or h<=0:continue
                image=e.get('image');frames=e.get('frames',[])
                if frames:image=frames[int(ui.time*max(.01,float(e.get('fps',12))))%len(frames)]
                if image:
                    texture=ui.world.resources.texture(ui.images[image]);f('glEnable',None,U)(0x0DE1);f('glBindTexture',None,U,U)(0x0DE1,texture)
                else:f('glDisable',None,U)(0x0DE1)
                color=e.get('color',[1,1,1,1]);f('glColor4f',None,F,F,F,F)(*color[:3],alpha*(color[3] if len(color)>3 else 1))
                a=math.radians(angle);c,s=math.cos(a),math.sin(a);cx=x+w*.5;cy=y+h*.5
                left,top,right,bottom=-w*.5,-h*.5,w*.5,h*.5
                if image and not frames and e.get('imageRect'):
                    ix,iy,iw,ih=e['imageRect'];sx=w/e['rect'][2];sy=h/e['rect'][3]
                    left=ix*sx-w*.5;top=iy*sy-h*.5;right=left+iw*sx;bottom=top+ih*sy
                f('glBegin',None,U)(7)
                for lx,ly,u,v in ((left,top,0,1),(right,top,1,1),(right,bottom,1,0),(left,bottom,0,0)):
                    f('glTexCoord2f',None,F,F)(u,v);f('glVertex2f',None,F,F)(ox+(cx+c*lx-s*ly)*scale,oy+(cy+s*lx+c*ly)*scale)
                f('glEnd',None)()
        finally:
            f('glPopMatrix',None)();f('glMatrixMode',None,U)(0x1701);f('glPopMatrix',None)();f('glMatrixMode',None,U)(0x1700)
            f('glUseProgram',None,U)(previous.value);f('glPopAttrib',None)()
