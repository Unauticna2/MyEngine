"""Greedy boundary mesh for static/kinematic voxel collision; native ASM BVH queries."""
from array import array
from engine_assets import MeshData

def boundary_mesh(grid):
    size=grid.size;pixels=grid.pixels;step=grid.cell_size;vertices=array('f')
    def solid(p):
        if any(p[k]<0 or p[k]>=size[k] for k in range(3)):return False
        return pixels[4*(p[0]+size[0]*(p[1]+size[1]*p[2]))+3]>=128
    for axis in range(3):
        u=(axis+1)%3;v=(axis+2)%3;nu,nv=size[u],size[v]
        for plane in range(size[axis]+1):
            mask=[0]*(nu*nv)
            for y in range(nv):
                for x in range(nu):
                    a=[0,0,0];a[u]=x;a[v]=y;a[axis]=plane-1;b=a[:];b[axis]=plane
                    sa,sb=solid(a),solid(b);mask[x+nu*y]=(1 if sa else -1) if sa!=sb else 0
            for y in range(nv):
                x=0
                while x<nu:
                    sign=mask[x+nu*y]
                    if not sign:x+=1;continue
                    width=1
                    while x+width<nu and mask[x+width+nu*y]==sign:width+=1
                    height=1
                    while y+height<nv and all(mask[xx+nu*(y+height)]==sign for xx in range(x,x+width)):height+=1
                    for yy in range(y,y+height):mask[x+nu*yy:x+width+nu*yy]=[0]*width
                    points=[];normal=[0,0,0];normal[axis]=sign
                    for xx,yy in ((x,y),(x+width,y),(x+width,y+height),(x,y+height)):
                        p=[0,0,0];p[axis]=plane;p[u]=xx;p[v]=yy;points.append(tuple((p[k]-size[k]*.5)*step for k in range(3)))
                    for tri in ((0,1,2),(0,2,3)):
                        if sign<0:tri=tuple(reversed(tri))
                        for i in tri:vertices.extend((*points[i],*normal,0,0))
                    x+=width
                    if len(vertices)//24>1_000_000:raise ValueError('Voxel collider exceeds one million triangles; split the volume')
    if not vertices:return None
    return MeshData(vertices,tuple(min(vertices[k::8]) for k in range(3)),tuple(max(vertices[k::8]) for k in range(3)))
