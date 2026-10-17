"""Python components and broadphase; integration, SAT, mesh BVH queries and impulses are ASM."""
from __future__ import annotations
import ctypes as C
from dataclasses import dataclass
import itertools
import math
from engine_assets import finite
from engine_collision import rotation_axes


def xyz(value, default=(0.,0.,0.)):
    if value is None:return tuple(default)
    if isinstance(value,dict):value=tuple(value.get(k,default[i]) for i,k in enumerate(('x','y','z')))
    value=tuple(value)
    if len(value)!=3:raise ValueError('Expected a three-component vector')
    return tuple(finite(x) for x in value)


def positive(value,name):
    value=finite(value)
    if value<=0:raise ValueError(f'{name} must be positive')
    return value


def dot(a,b):return sum(x*y for x,y in zip(a,b))
def cross(a,b):return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])


class Float4(C.Structure):
    _fields_=[('x',C.c_float),('y',C.c_float),('z',C.c_float),('w',C.c_float)]
    def __iter__(self):return iter((self.x,self.y,self.z))
    def set(self,*values):self.x,self.y,self.z=xyz(values);self.w=0
    def __repr__(self):return f'Vector3({self.x:g}, {self.y:g}, {self.z:g})'


class NativeBody(C.Structure):
    _fields_=[('position',Float4),('velocity',Float4),('force',Float4),('quaternion',Float4),
              ('angular_velocity',Float4),('torque',Float4),('half',Float4),
              ('axis0',Float4),('axis1',Float4),('axis2',Float4),('inverse_inertia',Float4),
              ('inverse_mass',C.c_float),('gravity_scale',C.c_float),('linear_damping',C.c_float),
              ('angular_damping',C.c_float),('friction',C.c_float),('restitution',C.c_float),
              ('flags',C.c_uint32),('grounded',C.c_uint32),('minimum',Float4),('maximum',Float4),('previous',Float4)]


class NativeContact(C.Structure):
    _fields_=[('a',C.c_void_p),('b',C.c_void_p),('normal',Float4),('point',Float4),
              ('penetration',C.c_float),('friction',C.c_float),('restitution',C.c_float),
              ('normal_impulse',C.c_float),('target_velocity',C.c_float),('initialized',C.c_uint32),('reserved',C.c_uint64)]


class NativePair(C.Structure):
    _fields_=[('a',C.c_void_p),('b',C.c_void_p)]
class Triangle(C.Structure):
    _fields_=[('a',Float4),('b',Float4),('c',Float4)]
class BVHNode(C.Structure):
    _fields_=[('minimum',Float4),('maximum',Float4),('left',C.c_uint32),('right',C.c_uint32),('first',C.c_uint32),('count',C.c_uint32)]
class MeshInstance(C.Structure):
    _fields_=[('nodes',C.c_void_p),('triangles',C.c_void_p),('body',C.c_void_p),('pad',C.c_uint64),
              ('position',Float4),('basis0',Float4),('basis1',Float4),('basis2',Float4),
              ('inverse0',Float4),('inverse1',Float4),('inverse2',Float4)]
assert C.sizeof(NativeBody)==256 and NativeBody.inverse_mass.offset==176
assert C.sizeof(NativeContact)==80 and NativeContact.penetration.offset==48
assert C.sizeof(BVHNode)==48 and C.sizeof(Triangle)==48 and C.sizeof(MeshInstance)==144


class NativePhysics:
    def __init__(self,core):
        prefix=getattr(core,'physics_prefix','')
        specs={
          'PhysicsPrepare':([C.c_void_p,C.c_uint32],None),
          'PhysicsIntegrate':([C.c_void_p,C.c_uint32,C.c_void_p],None),
          'PhysicsBoxBox':([C.c_void_p,C.c_void_p,C.c_void_p],C.c_int),
          'PhysicsBoxTriangle':([C.c_void_p,C.c_void_p,C.c_void_p,C.c_void_p],C.c_int),
          'PhysicsBoxContacts':([C.c_void_p,C.c_uint32,C.c_void_p,C.c_uint32],C.c_uint32),
          'PhysicsMeshContacts':([C.c_void_p,C.c_void_p,C.c_void_p,C.c_uint32],C.c_uint32),
          'PhysicsSolve':([C.c_void_p,C.c_uint32,C.c_uint32],None)}
        for name,(args,result) in specs.items():
            f=getattr(core.dll,prefix+name);f.argtypes=args;f.restype=result
            setattr(self,name,f)


def quaternion(euler):
    x,y,z=(math.radians(v)*.5 for v in euler)
    sx,cx,sy,cy,sz,cz=math.sin(x),math.cos(x),math.sin(y),math.cos(y),math.sin(z),math.cos(z)
    return Float4(sx*cy*cz-cx*sy*sz,cx*sy*cz+sx*cy*sz,cx*cy*sz-sx*sy*cz,cx*cy*cz+sx*sy*sz)


def euler_from_body(b):
    a,b1,c=b.axis0,b.axis1,b.axis2
    y=math.asin(max(-1.,min(1.,-a.z)))
    if abs(math.cos(y))>1e-5:x=math.atan2(b1.z,c.z);z=math.atan2(a.y,a.x)
    else:x=0.;z=math.atan2(-b1.x,b1.y)
    return tuple(math.degrees(v) for v in (x,y,z))


class MeshGeometry:
    """One local-space triangle BVH per model layer, shared by all instances."""
    def __init__(self,mesh):
        vertices=mesh.vertices
        count=len(vertices)//24
        bounds=[]
        for i in range(count):
            o=i*24
            lo=tuple(min(vertices[o+j],vertices[o+8+j],vertices[o+16+j]) for j in range(3))
            hi=tuple(max(vertices[o+j],vertices[o+8+j],vertices[o+16+j]) for j in range(3))
            bounds.append((lo,hi,tuple((a+b)*.5 for a,b in zip(lo,hi))))
        nodes=[];order=[]
        def build(ids):
            n=len(nodes);nodes.append(None)
            lo=tuple(min(bounds[i][0][k] for i in ids) for k in range(3))
            hi=tuple(max(bounds[i][1][k] for i in ids) for k in range(3))
            if len(ids)<=8:
                first=len(order);order.extend(ids)
                nodes[n]=BVHNode(Float4(*lo),Float4(*hi),0,0,first,len(ids))
            else:
                axis=max(range(3),key=lambda k:hi[k]-lo[k]);ids.sort(key=lambda i:bounds[i][2][axis])
                mid=len(ids)//2;left=build(ids[:mid]);right=build(ids[mid:])
                nodes[n]=BVHNode(Float4(*lo),Float4(*hi),left,right,0,0)
            return n
        if not count:raise ValueError('Mesh collider has no triangles')
        build(list(range(count)))
        self.nodes=(BVHNode*len(nodes))(*nodes)
        self.triangles=(Triangle*count)()
        for i,source in enumerate(order):
            o=source*24
            self.triangles[i]=Triangle(*(Float4(*vertices[o+j:o+j+3]) for j in (0,8,16)))
        self.minimum,self.maximum=mesh.minimum,mesh.maximum


@dataclass
class Collider:
    size:tuple|None=None
    center:tuple|None=None
    is_trigger:bool=False
    enabled:bool=True
    w_size:float|None=None
    kind:str='box'
    layer:int=0
    mask:int=0xffffffff
    friction:float=.6
    restitution:float=0.
    @property
    def isTrigger(self):return self.is_trigger
    @isTrigger.setter
    def isTrigger(self,v):self.is_trigger=bool(v)
    @classmethod
    def from_json(cls,data):
        if data is None or data is False:return None
        if data is True:data={}
        if isinstance(data,str):data={'type':data}
        if not isinstance(data,dict):raise ValueError('Collider must be a dictionary, box, mesh or null')
        kind=data.get('type',data.get('kind','box')).lower()
        if kind not in ('box','mesh','voxel'):raise ValueError('Collider type must be box, mesh or voxel')
        size=xyz(data['size']) if data.get('size') is not None else None
        if size and min(size)<=0:raise ValueError('Collider size must be positive')
        center=xyz(data['center']) if data.get('center') is not None else None
        ws=data.get('wSize',data.get('w_size'))
        if ws is not None:ws=positive(ws,'wSize')
        layer=int(data.get('layer',0));mask=int(data.get('mask',0xffffffff))
        if not 0<=layer<32 or not 0<=mask<=0xffffffff:raise ValueError('Invalid collision layer/mask')
        friction=max(0.,finite(data.get('friction',.6)));bounce=finite(data.get('restitution',0))
        if not 0<=bounce<=1:raise ValueError('Restitution must be in 0..1')
        return cls(size,center,bool(data.get('isTrigger',data.get('is_trigger',False))),
                   bool(data.get('enabled',True)),ws,kind,layer,mask,friction,bounce)


class Rigidbody:
    """State belongs to the ASM body pool. Angular velocity and torque are in radians."""
    def __init__(self,owner,**config):
        self.owner=owner
        self._native=owner.world.physics.body(owner)
        self._mass=1.;self._kinematic=False;self._freeze_rotation=False;self._use_gravity=True
        self.mass=config.pop('mass',1.)
        self.is_kinematic=config.pop('isKinematic',config.pop('is_kinematic',config.pop('kinematic',False)))
        self.freeze_rotation=config.pop('freezeRotation',config.pop('freeze_rotation',False))
        self.use_gravity=config.pop('useGravity',config.pop('use_gravity',True))
        self.gravity_scale=config.pop('gravityScale',config.pop('gravity_scale',1.))
        self.linear_damping=config.pop('linearDamping',config.pop('linear_damping',.05))
        self.angular_damping=config.pop('angularDamping',config.pop('angular_damping',.1))
        self.friction=config.pop('friction',.6)
        self.restitution=config.pop('restitution',0.)
        self.velocity=config.pop('velocity',(0,0,0))
        self.angular_velocity=config.pop('angularVelocity',config.pop('angular_velocity',(0,0,0)))
        if config:raise ValueError('Unknown rigidbody settings: '+', '.join(config))
    def _check(self):
        self.owner.world.assert_thread()
        if getattr(self.owner,'destroyed',False) and not getattr(self.owner,'_in_destroy',False):raise ReferenceError('Object has been destroyed')
    @property
    def mass(self):return self._mass
    @mass.setter
    def mass(self,v):
        v=positive(v,'mass')
        if v<.0001:raise ValueError('mass must be at least 0.0001')
        self._mass=v
    @property
    def is_kinematic(self):return self._kinematic
    @is_kinematic.setter
    def is_kinematic(self,v):
        if not v and getattr(getattr(self.owner,'collider',None),'kind',None) in ('mesh','voxel'):
            raise ValueError('A triangle mesh is static/kinematic; use a box collider for dynamic bodies')
        self._kinematic=bool(v)
    @property
    def use_gravity(self):return self._use_gravity
    @use_gravity.setter
    def use_gravity(self,v):self._use_gravity=bool(v)
    @property
    def freeze_rotation(self):return self._freeze_rotation
    @freeze_rotation.setter
    def freeze_rotation(self,v):self._freeze_rotation=bool(v)
    @property
    def velocity(self):self._check();return self._native.velocity
    @velocity.setter
    def velocity(self,v):self._check();self._native.velocity.set(*xyz(v))
    @property
    def angular_velocity(self):self._check();return self._native.angular_velocity
    @angular_velocity.setter
    def angular_velocity(self,v):self._check();self._native.angular_velocity.set(*xyz(v))
    @property
    def grounded(self):return bool(self._native.grounded)
    def _scalar(name,low=0,high=1e6):
        def get(self):return getattr(self._native,name)
        def set(self,v):
            self._check();v=finite(v)
            if not low<=v<=high:raise ValueError(f'{name}: expected {low}..{high}')
            setattr(self._native,name,v)
        return property(get,set)
    @property
    def gravity_scale(self):return self._gravity_scale
    @gravity_scale.setter
    def gravity_scale(self,v):
        v=finite(v)
        if not -1000<=v<=1000:raise ValueError('gravity_scale must be -1000..1000')
        self._gravity_scale=v
    linear_damping=_scalar('linear_damping')
    angular_damping=_scalar('angular_damping')
    friction=_scalar('friction',0,10)
    restitution=_scalar('restitution',0,1)
    isKinematic=is_kinematic
    useGravity=use_gravity
    freezeRotation=freeze_rotation
    def add_force(self,value,mode='force'):
        self._check();value=xyz(value)
        if self.is_kinematic:return
        if mode in ('force','acceleration'):
            f=self._native.force;k=self.mass if mode=='acceleration' else 1.
        elif mode in ('impulse','velocity_change'):
            f=self._native.velocity;k=1/self.mass if mode=='impulse' else 1.
        else:raise ValueError('mode: force, acceleration, impulse, velocity_change')
        f.set(*(a+b*k for a,b in zip(f,value)))
    def add_torque(self,value):
        self._check()
        if not self.is_kinematic:self._native.torque.set(*(a+b for a,b in zip(self._native.torque,xyz(value))))
    def add_force_at_position(self,force,position):
        force=xyz(force);position=xyz(position);self.add_force(force)
        self.add_torque(cross(tuple(p-c for p,c in zip(position,self._native.position)),force))
    def move_position(self,value):self._check();self.owner.position=xyz(value)
    def move_rotation(self,value):
        self._check()
        if self.owner.is_player:raise ValueError('Set camera.pitch/yaw; the player collider stays upright')
        self.owner.rotation=xyz(value)
    def teleport(self,position,rotation=None,reset_velocity=True):
        self.move_position(position)
        if rotation is not None:self.move_rotation(rotation)
        if reset_velocity:self.velocity=(0,0,0);self.angular_velocity=(0,0,0)


@dataclass(frozen=True)
class Collision:
    other:object
    point:tuple
    normal:tuple
    penetration:float
    impulse:float


class PhysicsWorld:
    def __init__(self,world):
        self.world=world;self.native=NativePhysics(world.core)
        self.bodies=(NativeBody*4097)()
        for b in self.bodies:b.quaternion.w=1.;b.half.set(.5,.5,.5)
        self.base=C.addressof(self.bodies)
        self.gravity=(0.,-9.81,0.)
        self.fixed_delta_time=1/120
        self.solver_iterations=10
        self.max_substeps=8
        self.enabled=True;self.accumulator=0.;self.fixed_time=0.
        self.geometry={};self.voxel_geometry={};self.instances={};self.offsets={};self.rotations={};self.initialized=set()
        self.previous={};self._warned_capacity=False
        self._mesh_out=(NativeContact*1024)()
    def body(self,actor):return self.bodies[actor.id+1]
    def address(self,actor):return self.base+(actor.id+1)*256
    def geometry_for(self,layer):
        if not layer.geometry.vertices:return None
        key=layer.id
        if key not in self.geometry:
            mesh=layer.geometry
            if not hasattr(mesh,'_physics_geometry'):mesh._physics_geometry=MeshGeometry(mesh)
            self.geometry[key]=mesh._physics_geometry
        return self.geometry[key]
    def configure(self,data):
        if not data:return
        self.gravity=xyz(data.get('gravity',self.gravity))
        h=positive(data.get('fixedDeltaTime',self.fixed_delta_time),'fixedDeltaTime')
        if not 1/1000<=h<=1/20:raise ValueError('fixedDeltaTime must be 0.001..0.05')
        self.fixed_delta_time=h
        self.solver_iterations=max(1,min(32,int(data.get('solverIterations',10))))
        self.max_substeps=max(1,min(16,int(data.get('maxSubsteps',8))))
    def voxel_geometry_for(self,actor):
        if not actor.voxels:raise ValueError(f'{actor.name}: voxel collider requires a voxel model')
        grid=actor.voxels.grid;old=self.voxel_geometry.get(actor.uid)
        if old is None or old[0] is not grid or old[1]!=grid.revision:
            from engine_voxel_physics import boundary_mesh
            key=(grid.size,grid.cell_size)
            if key not in grid._storage.colliders:
                mesh=boundary_mesh(grid);grid._storage.colliders[key]=MeshGeometry(mesh) if mesh else None
            g=grid._storage.colliders[key]
            self.voxel_geometry[actor.uid]=(grid,grid.revision,g)
        return self.voxel_geometry[actor.uid][2]
    def _actors(self):return [self.world.camera,*self.world.entities]
    def _count(self):return self.world._native_count+1
    def _sync(self,h):
        active={}
        for actor in self._actors():
            b=self.body(actor);b.flags=0
            if getattr(actor,'destroyed',False) or not actor.active:continue
            if not actor.is_player:
                actor.sync()
                if actor.layer is None:continue
            col=actor.collider;rb=actor.rigidbody
            if col is None and rb is None:continue
            w=getattr(actor,'w',self.world.camera.w)
            if col and col.w_size is not None and abs(self.world.camera.w-w)>col.w_size*.5:continue
            voxel=getattr(actor,'voxels',None)
            if voxel and voxel.w_size is not None and abs(self.world.camera.w-w)>voxel.w_size*.5:continue
            scale=(1,1,1) if actor.is_player else xyz(actor.scale)
            if min(abs(v) for v in scale)<1e-5:raise ValueError(f'{actor.name}: zero physics scale')
            rotation=(0,0,0) if actor.is_player else xyz(actor.rotation)
            axes=rotation_axes(rotation)
            layer=None if actor.is_player or not actor.layers else actor.layers[actor.layer]
            default_size=tuple(max(1e-4,hi-lo) for lo,hi in zip(layer.minimum,layer.maximum)) if layer else (1,1,1)
            default_center=tuple((lo+hi)*.5 for lo,hi in zip(layer.minimum,layer.maximum)) if layer else (0,0,0)
            if voxel and (layer is None or col and col.kind=='voxel'):
                default_size=tuple(n*voxel.grid.cell_size for n in voxel.grid.size);default_center=(0,0,0)
            geometry=None
            if col and col.kind in ('mesh','voxel'):
                if col.kind=='mesh' and not layer:raise ValueError(f'{actor.name}: mesh collider requires a model')
                if rb and not rb.is_kinematic:raise ValueError('Dynamic triangle meshes are not supported; use a box')
                geometry=self.voxel_geometry_for(actor) if col.kind=='voxel' else self.geometry_for(layer)
                if geometry is None:continue
                center=(0,0,0);size=default_size
            else:
                center=col.center if col and col.center is not None else default_center
                size=col.size if col and col.size is not None else default_size
            size=xyz(size);center=xyz(center)
            if min(size)<=0:raise ValueError('Collider size must be positive')
            offset=tuple(sum(axes[i][j]*center[i]*scale[i] for i in range(3)) for j in range(3))
            position=tuple(a+b0 for a,b0 in zip(xyz(actor.position),offset))
            if rb and rb.is_kinematic:
                b.velocity.set(*( (v-old)/h if actor.uid in self.initialized else 0. for v,old in zip(position,b.position)))
                oldrot=self.rotations.get(actor.uid,rotation)
                b.angular_velocity.set(*(math.radians((v-old+180)%360-180)/h for v,old in zip(rotation,oldrot)))
            elif rb is None:b.velocity.set(0,0,0);b.angular_velocity.set(0,0,0)
            b.position.set(*position);b.half.set(*(abs(s*t)*.5 for s,t in zip(size,scale)))
            if self.rotations.get(actor.uid)!=rotation or actor.uid not in self.initialized:b.quaternion=quaternion(rotation)
            self.rotations[actor.uid]=rotation;self.offsets[actor.uid]=(center,scale)
            self.initialized.add(actor.uid)
            b.flags=1
            b.inverse_mass=0 if rb is None or rb.is_kinematic else 1/rb.mass
            if rb:
                if not rb.is_kinematic:b.flags|=2
                if rb.freeze_rotation or actor.is_player:b.flags|=4
                b.gravity_scale=rb.gravity_scale if rb.use_gravity else 0.
                for values in (b.velocity,b.angular_velocity,b.force,b.torque):xyz(values)
            else:
                b.gravity_scale=0;b.friction=col.friction if col else .6;b.restitution=col.restitution if col else 0
            if col and col.enabled:
                if not 0<=int(col.layer)<32 or not 0<=int(col.mask)<=0xffffffff:raise ValueError('Collision layer/mask')
                active[actor.id]=actor
                if col.kind in ('mesh','voxel'):
                    g=geometry;m=MeshInstance(C.addressof(g.nodes),C.addressof(g.triangles),self.address(actor),0)
                    m.position.set(*xyz(actor.position))
                    for i in range(3):
                        getattr(m,f'basis{i}').set(*(x*scale[i] for x in axes[i]))
                        getattr(m,f'inverse{i}').set(*(x/scale[i] for x in axes[i]))
                    self.instances[actor.id]=m
        return active
    def _pull(self,actors):
        for a in actors:
            rb=a.rigidbody
            if not rb or rb.is_kinematic or not self.body(a).flags&1:continue
            b=self.body(a)
            rotation=euler_from_body(b)
            center,scale=self.offsets[a.uid]
            axes=(tuple(b.axis0),tuple(b.axis1),tuple(b.axis2))
            offset=tuple(sum(axes[i][j]*center[i]*scale[i] for i in range(3)) for j in range(3))
            pos=tuple(v-d for v,d in zip(b.position,offset))
            if a.is_player:a.position.set(*pos)
            else:a.position=pos;a.rotation=rotation
            self.rotations[a.uid]=(0,0,0) if a.is_player else tuple(a.rotation)
    @staticmethod
    def _allowed(a,b):
        ac,bc=a.collider,b.collider
        if not (ac.mask&(1<<bc.layer) and bc.mask&(1<<ac.layer)):return False
        aw,bw=ac.w_size,bc.w_size
        if aw is not None and bw is not None and abs(a.w-b.w)>(aw+bw)*.5:return False
        return ac.is_trigger or bc.is_trigger or (a.rigidbody and not a.rigidbody.is_kinematic) or (b.rigidbody and not b.rigidbody.is_kinematic)
    def _box_pairs(self,actors):
        grid={};large=[];candidates=set();boxes={i:a for i,a in actors.items() if a.collider.kind=='box'}
        for i,a in boxes.items():
            b=self.body(a);lo=[math.floor(v/4) for v in b.minimum];hi=[math.floor(v/4) for v in b.maximum]
            if math.prod(hi[k]-lo[k]+1 for k in range(3))>512:large.append(i);continue
            for cell in itertools.product(*(range(lo[k],hi[k]+1) for k in range(3))):grid.setdefault(cell,[]).append(i)
        def add(i,j):
            if i!=j and self._allowed(boxes[i],boxes[j]):candidates.add(tuple(sorted((i,j))))
        for group in grid.values():
            for i,j in itertools.combinations(group,2):add(i,j)
        for i in large:
            for j in boxes:add(i,j)
        return [NativePair(self.address(boxes[i]),self.address(boxes[j])) for i,j in sorted(candidates)]
    def _contacts(self,actors):
        contacts=[];pairs=self._box_pairs(actors)
        if pairs:
            raw=(NativePair*len(pairs))(*pairs);out=(NativeContact*len(pairs))()
            n=self.native.PhysicsBoxContacts(raw,len(raw),out,len(out));contacts.extend(out[:n])
        meshes=[a for a in actors.values() if a.collider.kind in ('mesh','voxel')]
        for a in actors.values():
            if a.collider.kind!='box':continue
            for m in meshes:
                if not self._allowed(a,m):continue
                n=self.native.PhysicsMeshContacts(self.address(a),C.byref(self.instances[m.id]),self._mesh_out,len(self._mesh_out))
                if n==len(self._mesh_out) and not self._warned_capacity:
                    self.world.log('Physics: triangle contact buffer filled; use simpler collision geometry for very large boxes')
                    self._warned_capacity=True
                # Adjacent coplanar triangles must not apply the same correction many times.
                groups=[]
                for contact in self._mesh_out[:n]:
                    c=NativeContact.from_buffer_copy(contact)
                    for j,old in enumerate(groups):
                        if dot(c.normal,old.normal)>.995:
                            if c.penetration>old.penetration:groups[j]=c
                            break
                    else:groups.append(c)
                contacts.extend(groups)
        return contacts
    def _events(self,current):
        old=self.previous;self.previous=current
        for key,(a,b,c,trigger) in current.items():
            event='stay' if key in old else 'enter'
            self._send(event,a,b,c,trigger)
        for key,(a,b,c,trigger) in old.items():
            if key not in current:self._send('exit',a,b,c,trigger)
    def _send(self,event,a,b,c,trigger):
        for owner,other,sign in ((a,b,1),(b,a,-1)):
            if getattr(owner,'destroyed',False):continue
            arg=other if trigger else Collision(other,tuple(c.point),tuple(v*sign for v in c.normal),float(c.penetration),float(c.normal_impulse))
            for script in tuple(getattr(owner,'scripts',())):script.call(('on_trigger_' if trigger else 'on_collision_')+event,arg)
    def step(self,h):
        actors=self._sync(h);all_actors=self._actors();count=self._count()
        self.native.PhysicsPrepare(self.bodies,count)
        max_ratio=1.
        forces={}
        for a in all_actors:
            b=self.body(a)
            if b.flags&3==3:
                max_ratio=max(max_ratio,math.sqrt(dot(b.velocity,b.velocity))*h/max(.0001,min(b.half)*.45))
                forces[a.id]=(tuple(b.force),tuple(b.torque))
        substeps=min(max(1,min(16,int(self.max_substeps))),max(1,math.ceil(max_ratio)))
        dt=h/substeps;settings=(C.c_float*4)(*xyz(self.gravity),dt);events={}
        for _ in range(substeps):
            for i,(f,t) in forces.items():self.bodies[i+1].force.set(*f);self.bodies[i+1].torque.set(*t)
            self.native.PhysicsIntegrate(self.bodies,count,settings)
            self.native.PhysicsPrepare(self.bodies,count)
            detected=self._contacts(actors);solid=[]
            for c in detected:
                ai=(c.a-self.base)//256-1;bi=(c.b-self.base)//256-1
                a,b=actors[ai],actors[bi];trigger=a.collider.is_trigger or b.collider.is_trigger
                if not trigger:solid.append(c)
                key=(*sorted((a.uid,b.uid)),bool(trigger))
                events[key]=(a,b,c,trigger)
            if solid:
                out=(NativeContact*len(solid))(*solid)
                self.native.PhysicsSolve(out,len(out),int(self.solver_iterations))
                for c in out:
                    ai=(c.a-self.base)//256-1;bi=(c.b-self.base)//256-1;a,b=actors[ai],actors[bi]
                    events[(*sorted((a.uid,b.uid)),False)]=(a,b,c,False)
            self.native.PhysicsPrepare(self.bodies,count)
        self._pull(all_actors)
        self.fixed_time+=h
        self._events(events)
    def tick(self,dt,before_step):
        if not self.enabled:return
        h=positive(self.fixed_delta_time,'fixed_delta_time')
        if not .001<=h<=.05:raise ValueError('fixed_delta_time must be 0.001..0.05')
        self.accumulator=min(self.accumulator+dt,.1)
        steps=0
        while self.accumulator+1e-9>=h and steps<100:
            before_step(h)
            self.step(h)
            self.accumulator-=h;steps+=1
    def forget(self,actor):
        b=self.body(actor);C.memset(C.addressof(b),0,256);b.quaternion.w=1;b.half.set(.5,.5,.5)
        self.instances.pop(actor.id,None);self.initialized.discard(actor.uid)
        self.voxel_geometry.pop(actor.uid,None)
        self.rotations.pop(actor.uid,None);self.offsets.pop(actor.uid,None)
    def close(self):self.previous.clear();self.geometry.clear();self.voxel_geometry.clear();self.instances.clear()
