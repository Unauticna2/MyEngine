"""Alpha-blended UI sprites with shared rendering / pointer scaling."""
import ctypes as C,math
from engine_gl import GL,I,U,F,P
class UIRenderer:
    def __init__(self,gl=None):self.gl=gl or GL()
    def draw(self,ui):
        gl=self.gl;f=gl.fn;viewport=(I*4)();previous=I()
        f('glGetIntegerv',None,U,P)(0x0BA2,viewport);f('glGetIntegerv',None,U,P)(0x8B8D,C.byref(previous));width,height=viewport[2:4]
        if not width or not height:return
        sx,sy,ox,oy=ui.transform(width,height)
        f('glPushAttrib',None,U)(0xfffff);f('glUseProgram',None,U)(0)
        f('glMatrixMode',None,U)(0x1701);f('glPushMatrix',None)();f('glLoadIdentity',None)()
        f('glOrtho',None,*([C.c_double]*6))(0,width,height,0,-1,1)
        f('glMatrixMode',None,U)(0x1700);f('glPushMatrix',None)();f('glLoadIdentity',None)()
        try:
            for cap in (0x0B71,0x0B50,0x0B44,0x0BC0,0x0C11):f('glDisable',None,U)(cap)
            f('glDepthMask',None,C.c_ubyte)(0);f('glEnable',None,U)(0x0BE2);f('glBlendFunc',None,U,U)(0x0302,0x0303)
            for unit in range(8):f('glActiveTexture',None,U)(0x84C0+unit);f('glDisable',None,U)(0x0DE1);f('glDisable',None,U)(0x806F)
            f('glActiveTexture',None,U)(0x84C0)
            # Clip moving slides to the UI canvas, including letterbox borders.
            f('glEnable',None,U)(0x0C11)
            from engine_ui_scaling import clip_rect
            clipx,clipy,cw,ch=clip_rect(ui.data['width'],ui.data['height'],width,height,(sx,sy,ox,oy))
            f('glScissor',None,I,I,I,I)(viewport[0]+clipx,viewport[1]+clipy,cw,ch)
            items=ui.render_items()
            if ui.content.textures:ui.content.textures.pump()
            from engine_ui_layout import anchored
            for e,pose in items:
                if anchored(e):f('glScissor',None,I,I,I,I)(viewport[0],viewport[1],width,height)
                else:f('glScissor',None,I,I,I,I)(viewport[0]+clipx,viewport[1]+clipy,cw,ch)
                x,y,w,h,angle,alpha=pose
                if alpha<=0 or w<=0 or h<=0:continue
                image=e.get('image');frames=e.get('frames',[])
                if frames:image=frames[ui.frame_index(e)]
                if e.get('_textKey'):
                    entry=ui.content.textures.cache.get(e['_textKey'])
                    if entry is None:continue
                    texture=entry[0];f('glEnable',None,U)(0x0DE1);f('glBindTexture',None,U,U)(0x0DE1,texture)
                elif image:
                    if ui.assets:
                        name=ui.images[image];texture=ui.assets.handles.get(name)
                        if texture is None:
                            if name not in ui.assets.failed:continue
                            image=None
                    else:texture=ui.world.resources.texture(ui.images[image])
                    if image:f('glEnable',None,U)(0x0DE1);f('glBindTexture',None,U,U)(0x0DE1,texture)
                    else:f('glDisable',None,U)(0x0DE1)
                else:f('glDisable',None,U)(0x0DE1)
                color=e.get('color',[1,1,1,1]);f('glColor4f',None,F,F,F,F)(*color[:3],alpha*(color[3] if len(color)>3 else 1))
                a=math.radians(angle);c,s=math.cos(a),math.sin(a);cx=x+w*.5;cy=y+h*.5
                left,top,right,bottom=-w*.5,-h*.5,w*.5,h*.5
                if image and not frames and e.get('imageRect'):
                    ix,iy,iw,ih=e['imageRect'];esx=w/e['rect'][2];esy=h/e['rect'][3]
                    left=ix*esx-w*.5;top=iy*esy-h*.5;right=left+iw*esx;bottom=top+ih*esy
                f('glBegin',None,U)(7)
                for lx,ly,u,v in ((left,top,0,1),(right,top,1,1),(right,bottom,1,0),(left,bottom,0,0)):
                    f('glTexCoord2f',None,F,F)(u,v);f('glVertex2f',None,F,F)(ox+(cx+c*lx-s*ly)*sx,oy+(cy+s*lx+c*ly)*sy)
                f('glEnd',None)()
            if ui.loading and ui.assets:
                sid=ui._pending_slide[0] if ui._pending_slide else ui.active
                progress=ui.assets.progress(ui.slide_images(sid))
                f('glDisable',None,U)(0x0C11);f('glDisable',None,U)(0x0DE1)
                for length,color in ((width,(.1,.1,.1,.85)),(max(6,width*progress),(.2,.8,1.,1.))):
                    f('glColor4f',None,F,F,F,F)(*color);f('glBegin',None,U)(7)
                    for x,y in ((0,height-4),(length,height-4),(length,height),(0,height)):f('glVertex2f',None,F,F)(x,y)
                    f('glEnd',None)()
        finally:
            f('glPopMatrix',None)();f('glMatrixMode',None,U)(0x1701);f('glPopMatrix',None)();f('glMatrixMode',None,U)(0x1700)
            f('glUseProgram',None,U)(previous.value);f('glPopAttrib',None)()
