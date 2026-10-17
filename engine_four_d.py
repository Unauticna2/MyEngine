"""Slices of the existing layered .4d format with XW/YW/ZW plane rotations.

Each OBJ surface triangle is extruded over its layer's W interval, then the
triangular prism is intersected with the camera's W hyperplane. This preserves
the existing piecewise layer definition; it does not invent correspondence
between unrelated meshes in neighbouring layers.
"""
from array import array
import math
from engine_assets import MeshData

EDGES=((0,1),(1,2),(2,0),(3,4),(4,5),(5,3),(0,3),(1,4),(2,5))
def dot(a,b):return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]
def sub(a,b):return (a[0]-b[0],a[1]-b[1],a[2]-b[2])
def cross(a,b):return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
def unit(v):
    length=math.sqrt(dot(v,v))
    return tuple(x/length for x in v) if length>1e-12 else (0.,0.,0.)
def rotation4(angles):
    m=[[float(r==c) for c in range(4)] for r in range(4)]
    for axis,angle in enumerate(angles):
        a=math.radians(angle);c=math.cos(a);s=math.sin(a)
        row,w=m[axis][:],m[3][:]
        m[axis]=[c*x-s*y for x,y in zip(row,w)]
        m[3]=[s*x+c*y for x,y in zip(row,w)]
    return m
def transform(m,v):
    x,y,z,w=v
    return tuple(r[0]*x+r[1]*y+r[2]*z+r[3]*w for r in m)

def prepared(mesh):
    cache=getattr(mesh,'_slice_vertices',None)
    if cache is None:
        lookup={};vertices=[];indices=[];raw=mesh.vertices
        for o in range(0,len(raw),8):
            v=tuple(raw[o:o+8]);i=lookup.get(v)
            if i is None:i=len(vertices);lookup[v]=i;vertices.append(v)
            indices.append(i)
        cache=(vertices,[tuple(indices[i:i+3]) for i in range(0,len(indices),3)])
        mesh._slice_vertices=cache
    return cache


def slice_layers(layers,spacing,w_scale,angles,scale,cut):
    m=rotation4(angles);output=array('f')
    for i,layer in enumerate(layers):
        mesh=layer.geometry
        low=(i-.5)*spacing*w_scale;high=(i+.5)*spacing*w_scale
        # Reject whole layers and triangles in W before transforming XYZ.
        coeff=tuple(m[3][k]*scale[k] for k in range(3))
        wl,wh=sorted((m[3][3]*low,m[3][3]*high))
        bounds=[sorted((coeff[k]*mesh.minimum[k],coeff[k]*mesh.maximum[k])) for k in range(3)]
        if cut<sum(b[0] for b in bounds)+wl-1e-8 or cut>sum(b[1] for b in bounds)+wh+1e-8:continue
        source,triangles=prepared(mesh)
        ws=[coeff[0]*v[0]+coeff[1]*v[1]+coeff[2]*v[2] for v in source]
        transformed={}
        for ids in triangles:
            wa,wb,wc=(ws[j] for j in ids)
            if cut<min(wa,wb,wc)+wl-1e-8 or cut>max(wa,wb,wc)+wh+1e-8:continue
            vertices=[source[j] for j in ids];points=[]
            for side,w in enumerate((low,high)):
                for j in ids:
                    cachekey=(j,side);p=transformed.get(cachekey)
                    if p is None:
                        v=source[j];p=transform(m,(v[0]*scale[0],v[1]*scale[1],v[2]*scale[2],w));transformed[cachekey]=p
                    points.append(p)
            if cut<min(p[3] for p in points)-1e-8 or cut>max(p[3] for p in points)+1e-8:continue
            hits=[]
            def add(p,uv):
                if not any(dot(sub(p,q[0]),sub(p,q[0]))<1e-14 for q in hits):hits.append((p,uv))
            for a,b in EDGES:
                pa,pb=points[a],points[b];wa,wb=pa[3]-cut,pb[3]-cut
                va,vb=vertices[a%3],vertices[b%3]
                if abs(wa)<1e-8:add(pa[:3],tuple(va[6:8]))
                if wa*wb<0:
                    t=wa/(wa-wb)
                    add(tuple(pa[k]+(pb[k]-pa[k])*t for k in range(3)),tuple(va[k]+(vb[k]-va[k])*t for k in (6,7)))
                if abs(wb)<1e-8:add(pb[:3],tuple(vb[6:8]))
            if len(hits)<3:continue
            center=tuple(sum(p[0][k] for p in hits)/len(hits) for k in range(3))
            # Surface normal transforms with inverse scale, then the 4D rotation.
            oldnormal=tuple(sum(v[k+3] for v in vertices)/3/scale[k] for k in range(3))
            normal=unit(transform(m,(*oldnormal,0))[:3])
            if dot(normal,normal)<.5:continue # Tangent/degenerate section.
            u=unit(sub(hits[0][0],center));v=cross(normal,u)
            hits.sort(key=lambda h:math.atan2(dot(sub(h[0],center),v),dot(sub(h[0],center),u)))
            localnormal=unit(tuple(normal[k]*scale[k] for k in range(3)))
            for j in range(1,len(hits)-1):
                tri=(hits[0],hits[j],hits[j+1])
                if dot(cross(sub(tri[1][0],tri[0][0]),sub(tri[2][0],tri[0][0])),normal)<0:tri=(tri[0],tri[2],tri[1])
                for p,uv in tri:output.extend((*[p[k]/scale[k] for k in range(3)],*localnormal,*uv))
    from engine_sections import append_caps
    append_caps(output,layers,spacing,w_scale,m,scale,cut)
    if not output:return None
    minimum=tuple(min(output[k::8]) for k in range(3));maximum=tuple(max(output[k::8]) for k in range(3))
    return MeshData(output,minimum,maximum)
