"""Oriented boxes: world-space broadphase grid and exact 15-axis SAT narrowphase."""
from dataclasses import dataclass
import itertools
import math


def dot(a,b):return sum(x*y for x,y in zip(a,b))
def rotation_axes(rotation):
    x,y,z=(math.radians(float(v)) for v in rotation)
    cx,sx,cy,sy,cz,sz=math.cos(x),math.sin(x),math.cos(y),math.sin(y),math.cos(z),math.sin(z)
    # Columns of Rz * Ry * Rx, identical to the native renderer.
    return ((cz*cy,sz*cy,-sy),
            (cz*sy*sx-sz*cx,sz*sy*sx+cz*cx,cy*sx),
            (cz*sy*cx+sz*sx,sz*sy*cx-cz*sx,cy*cx))

@dataclass
class Body:
    id: int
    owner: object
    center: tuple
    axes: tuple
    half: tuple
    trigger: bool
    w_min: float=-math.inf
    w_max: float=math.inf

    @property
    def bounds(self):
        extent=tuple(sum(abs(self.axes[i][j])*self.half[i] for i in range(3)) for j in range(3))
        return (tuple(self.center[j]-extent[j] for j in range(3)),
                tuple(self.center[j]+extent[j] for j in range(3)))


def make_body(id,owner,position,rotation,scale,size,center,trigger,w_range=(-math.inf,math.inf)):
    axes=rotation_axes(rotation)
    offset=tuple(float(center[i])*float(scale[i]) for i in range(3))
    c=tuple(float(position[j])+sum(axes[i][j]*offset[i] for i in range(3)) for j in range(3))
    half=tuple(abs(float(size[i])*float(scale[i]))*.5 for i in range(3))
    if not all(math.isfinite(v) for v in (*c,*half)) or min(half)<=0:
        raise ValueError('BoxCollider size/scale must be finite and nonzero')
    return Body(id,owner,c,axes,half,bool(trigger),*w_range)


def overlap(a:Body,b:Body):
    if a.w_max<b.w_min or b.w_max<a.w_min:return False
    r=[[dot(a.axes[i],b.axes[j]) for j in range(3)] for i in range(3)]
    ar=[[abs(r[i][j])+1e-7 for j in range(3)] for i in range(3)]
    d=tuple(b.center[i]-a.center[i] for i in range(3))
    t=[dot(d,a.axes[i]) for i in range(3)]
    for i in range(3):
        if abs(t[i])>a.half[i]+sum(b.half[j]*ar[i][j] for j in range(3)):return False
    for j in range(3):
        if abs(sum(t[i]*r[i][j] for i in range(3)))>b.half[j]+sum(a.half[i]*ar[i][j] for i in range(3)):return False
    for i in range(3):
        i1,i2=(i+1)%3,(i+2)%3
        for j in range(3):
            j1,j2=(j+1)%3,(j+2)%3
            ra=a.half[i1]*ar[i2][j]+a.half[i2]*ar[i1][j]
            rb=b.half[j1]*ar[i][j2]+b.half[j2]*ar[i][j1]
            if abs(t[i2]*r[i1][j]-t[i1]*r[i2][j])>ra+rb:return False
    return True


class TriggerSystem:
    def __init__(self,cell_size=4.0):
        self.cell_size=cell_size
        self.previous=set()
        self.owners={}

    def update(self,bodies):
        bodies={b.id:b for b in bodies}
        grid={};large=[]
        for b in bodies.values():
            low,high=b.bounds
            lo=[math.floor(v/self.cell_size) for v in low]
            hi=[math.floor(v/self.cell_size) for v in high]
            counts=[hi[i]-lo[i]+1 for i in range(3)]
            if math.prod(counts)>512:
                large.append(b.id);continue
            for c in itertools.product(*(range(lo[i],hi[i]+1) for i in range(3))):
                grid.setdefault(c,[]).append(b.id)
        candidates=set()
        for group in grid.values():
            for a,b in itertools.combinations(group,2):
                if bodies[a].trigger or bodies[b].trigger:candidates.add(tuple(sorted((a,b))))
        for a in large:
            for b in bodies:
                if a!=b and (bodies[a].trigger or bodies[b].trigger):candidates.add(tuple(sorted((a,b))))
        current={pair for pair in candidates if overlap(bodies[pair[0]],bodies[pair[1]])}
        owners={**self.owners,**{i:b.owner for i,b in bodies.items()}}
        events=[]
        for pair in sorted(current):
            events.append(('stay' if pair in self.previous else 'enter',owners[pair[0]],owners[pair[1]]))
        for pair in sorted(self.previous-current):
            events.append(('exit',owners[pair[0]],owners[pair[1]]))
        self.previous=current
        self.owners={i:b.owner for i,b in bodies.items()}
        return events
