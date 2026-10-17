"""Per-element anchors relative to the visible viewport, in reference slide units."""
import math

HORIZONTAL=('canvas','left','center','right','stretch')
VERTICAL=('canvas','top','center','bottom','stretch')

def anchors(value=None):
    value=value or {}
    h=value.get('horizontal','canvas');v=value.get('vertical','canvas')
    if h not in HORIZONTAL or v not in VERTICAL:raise ValueError('Unknown UI anchor')
    return {'horizontal':h,'vertical':v}

def anchored(element):
    a=anchors(element.get('anchors'))
    return a['horizontal']!='canvas' or a['vertical']!='canvas'

def rect(element,canvas,viewport,transform):
    x,y,w,h=map(float,element['rect']);a=anchors(element.get('anchors'))
    sx,sy,ox,oy=transform
    for axis,(ref,size,scale,offset,mode) in enumerate(zip(canvas,viewport,(sx,sy),(ox,oy),(a['horizontal'],a['vertical']))):
        if mode=='canvas':continue
        delta=size/scale-ref;shift=-offset/scale
        if mode=='center':shift+=delta*.5
        elif mode in ('right','bottom'):shift+=delta
        if axis==0:
            x+=shift
            if mode=='stretch':w=max(1,w+delta)
        else:
            y+=shift
            if mode=='stretch':h=max(1,h+delta)
    return x,y,w,h

def sub_pose(parent,relative,reference):
    x,y,w,h,angle,alpha=parent;rx,ry,rw,rh=relative
    kx=w/reference[0];ky=h/reference[1]
    dx=(rx+rw*.5)*kx-w*.5;dy=(ry+rh*.5)*ky-h*.5
    a=math.radians(angle);c=math.cos(a);s=math.sin(a)
    return x+w*.5+c*dx-s*dy-rw*kx*.5,y+h*.5+s*dx+c*dy-rh*ky*.5,rw*kx,rh*ky,angle,alpha
