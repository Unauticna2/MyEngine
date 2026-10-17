"""Planar end faces for piecewise-solid 4D layers. No third-party geometry library.

At a shared W boundary emit A minus B and B minus A, not internal walls.
Even/odd scan conversion supports concave contours, islands and holes.
"""
import math

def dot(a,b):return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]
def sub(a,b):return (a[0]-b[0],a[1]-b[1],a[2]-b[2])
def cross(a,b):return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
def unit(v):return tuple(x/math.sqrt(dot(v,v)) for x in v)

def segments(mesh,m,scale,w,cut,u,v):
    result=[];row=tuple(m[3][k]*scale[k] for k in range(3));target=cut-m[3][3]*w
    from engine_four_d import prepared,transform
    vertices,triangles=prepared(mesh)
    ds_all=[row[0]*q[0]+row[1]*q[1]+row[2]*q[2]-target for q in vertices]
    for ids in triangles:
        ds=[ds_all[j] for j in ids]
        if min(ds)>1e-8 or max(ds)<-1e-8 or max(abs(d) for d in ds)<1e-8:continue
        p=[(vertices[j][0]*scale[0],vertices[j][1]*scale[1],vertices[j][2]*scale[2]) for j in ids]
        hits=[]
        def add(q):
            if not any(dot(sub(q,r),sub(q,r))<1e-16 for r in hits):hits.append(q)
        for a,b in ((0,1),(1,2),(2,0)):
            if abs(ds[a])<1e-8:add(p[a])
            if ds[a]*ds[b]<0:
                t=ds[a]/(ds[a]-ds[b]);add(tuple(p[a][k]+(p[b][k]-p[a][k])*t for k in range(3)))
        if len(hits)!=2:continue
        q=[transform(m,(*x,w))[:3] for x in hits]
        a,b=[(dot(x,u),dot(x,v)) for x in q]
        if abs(a[1]-b[1])>1e-9:result.append((a,b)) # Horizontal edges do not cross a scan line.
    return result

def x_at(edge,y):
    a,b=edge;return a[0]+(b[0]-a[0])*(y-a[1])/(b[1]-a[1])

def difference_strips(a,b):
    """Yield (owner, trapezoid) covering the symmetric difference of contours."""
    edges=[(e,0) for e in a]+[(e,1) for e in b]
    ys={round(p[1],10) for e,_ in edges for p in e}
    # Split strips at crossing contours so left/right edge order cannot change.
    # Only compare edges whose Y intervals overlap, rather than a full A*B scan.
    ebounds=sorted((min(e[0][1],e[1][1]),max(e[0][1],e[1][1]),e) for e in b)
    for ea in a:
        alo=min(ea[0][1],ea[1][1]);ahi=max(ea[0][1],ea[1][1])
        for blo,bhi,eb in ebounds:
            if blo>=ahi:break
            if bhi<=alo:continue
            lo=max(alo,blo);hi=min(ahi,bhi)
            if hi-lo<1e-9:continue
            d0=x_at(ea,lo)-x_at(eb,lo);d1=x_at(ea,hi)-x_at(eb,hi)
            if d0*d1<0:ys.add(round(lo+(hi-lo)*d0/(d0-d1),10))
    ys=sorted(ys)
    events=sorted((min(e[0][1],e[1][1]),max(e[0][1],e[1][1]),i,e) for e,i in edges)
    active=[];index=0
    for low,high in zip(ys,ys[1:]):
        if high-low<1e-9:continue
        mid=(low+high)*.5
        while index<len(events) and events[index][0]<mid:
            active.append(events[index]);index+=1
        active=[e for e in active if e[1]>mid]
        hits=sorted((x_at(e,mid),i,e) for _,_,i,e in active)
        state=[False,False];previous=None;j=0
        while j<len(hits):
            x,_,edge=hits[j]
            if previous is not None and state[0]!=state[1] and x-previous[0]>1e-8:
                left=previous[1]
                yield (0 if state[0] else 1),((x_at(left,low),low),(x_at(edge,low),low),(x_at(edge,high),high),(x_at(left,high),high))
            k=j
            while k<len(hits) and abs(hits[k][0]-x)<1e-8:
                state[hits[k][1]]=not state[hits[k][1]];k+=1
            previous=(x,edge);j=k

def append_caps(output,layers,spacing,w_scale,m,scale,cut):
    n=tuple(m[k][3] for k in range(3));nn=dot(n,n)
    if nn<1e-14:return
    normal=unit(n);u=unit(cross(normal,(0,1,0) if abs(normal[1])<.8 else (1,0,0)));v=cross(normal,u)
    for boundary in range(len(layers)+1):
        w=(boundary-.5)*spacing*w_scale
        # n.xyz dot p.xyz + n.w * cut == original scaled W.
        origin=tuple(x*(w-m[3][3]*cut)/nn for x in n)
        a=segments(layers[boundary-1].geometry,m,scale,w,cut,u,v) if boundary else []
        b=segments(layers[boundary].geometry,m,scale,w,cut,u,v) if boundary<len(layers) else []
        for owner,polygon in difference_strips(a,b):
            sign=(1 if owner==0 else -1)*(1 if w_scale>0 else -1)
            outward=tuple(x*sign for x in normal);localnormal=unit(tuple(outward[k]*scale[k] for k in range(3)))
            points=[tuple(origin[k]+u[k]*p[0]+v[k]*p[1] for k in range(3)) for p in polygon]
            for ids in ((0,1,2),(0,2,3)):
                aa,bb,cc=(points[i] for i in ids)
                face=cross(sub(bb,aa),sub(cc,aa))
                if dot(face,face)<1e-18:continue
                if dot(face,outward)<0:ids=tuple(reversed(ids))
                for i in ids:output.extend((*[points[i][k]/scale[k] for k in range(3)],*localnormal,*polygon[i]))
