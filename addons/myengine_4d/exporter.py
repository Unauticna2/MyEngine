"""Blender geometry conversion. All bpy/mesh access remains on Blender's main thread."""
import math
from .hierarchy import group_layers,header,atomic_export

GEOMETRY={'MESH','CURVE','SURFACE','FONT','META'}

def number(value):
    value=float(value)
    if not math.isfinite(value) or abs(value)>1e6:raise ValueError('Non-finite / oversized geometry coordinate')
    return format(value,'.9g')

def write_mesh(out,obj,mesh,matrix,counts):
    mesh.calc_loop_triangles()
    if not mesh.loop_triangles:return 0
    vertex_offset,corner_offset,triangle_count=counts
    nv,nc=len(mesh.vertices),len(mesh.loops)
    nt=len(mesh.loop_triangles)
    if vertex_offset+nv>1_000_000 or corner_offset+nc>1_000_000 or triangle_count+nt>1_000_000:
        raise ValueError('A layer exceeds the engine geometry limit (1 million vertices/normals/triangles)')
    linear=matrix.to_3x3()
    if abs(linear.determinant())<1e-12:raise ValueError('Zero object scale: '+obj.name)
    normal_matrix=linear.inverted().transposed();mirrored=linear.determinant()<0
    out.write('o '+obj.name.replace('\r',' ').replace('\n',' ')+'\n')
    for vertex in mesh.vertices:
        out.write('v '+' '.join(number(v) for v in matrix @ vertex.co)+'\n')
    uv=mesh.uv_layers.active
    # Older Blender versions need an explicit split-normal calculation.
    # Newer versions calculate readable loop normals on demand.
    calculate=getattr(mesh,'calc_normals_split',None)
    if callable(calculate):calculate()
    # Each loop gets its own UV/normal index, preserving seams and sharp edges.
    for loop in mesh.loops:
        values=uv.data[loop.index].uv if uv else (0,0)
        out.write('vt '+' '.join(number(v) for v in values)+'\n')
    fallback={}
    for polygon in mesh.polygons:
        for li in polygon.loop_indices:
            fallback[li]=mesh.vertices[mesh.loops[li].vertex_index].normal if polygon.use_smooth else polygon.normal
    for loop in mesh.loops:
        source=getattr(loop,'normal',None)
        if source is None or source.length_squared<1e-20:source=fallback[loop.index]
        n=normal_matrix @ source
        if n.length_squared<1e-20:n=normal_matrix @ fallback[loop.index]
        n.normalize();out.write('vn '+' '.join(number(v) for v in n)+'\n')
    for tri in mesh.loop_triangles:
        loops=list(tri.loops)
        if mirrored:loops.reverse()
        refs=[]
        for li in loops:
            vi=vertex_offset+mesh.loops[li].vertex_index+1;ci=corner_offset+li+1
            refs.append(f'{vi}/{ci}/{ci}')
        out.write('f '+' '.join(refs)+'\n')
    counts[:]=[vertex_offset+nv,corner_offset+nc,triangle_count+nt]
    return nt

def export_hierarchy(context,root,path,spacing=.1,root_mode='AUTO',modifiers=True,include_hidden=False):
    from mathutils import Matrix
    if context.mode!='OBJECT':raise ValueError('Switch to Object Mode before exporting')
    groups=group_layers(root,root_mode);depsgraph=context.evaluated_depsgraph_get()
    # Blender Z-up -> engine Y-up; retain rotation/scale, put the root pivot at (0,0,0).
    axes=Matrix(((1,0,0,0),(0,0,1,0),(0,-1,0,0),(0,0,0,1)))
    origin=Matrix.Translation(-root.matrix_world.translation)
    def write(out):
        out.write(header(spacing,root_mode));total=0
        for depth,objects in enumerate(groups):
            if depth:out.write('+\n')
            out.write(f'# layer {depth} w={number(depth*spacing)}\n');counts=[0,0,0]
            for obj in objects:
                if obj.type not in GEOMETRY:continue
                if not include_hidden and not obj.visible_get(view_layer=context.view_layer):continue
                evaluated=obj.evaluated_get(depsgraph) if modifiers else obj
                mesh=evaluated.to_mesh(preserve_all_data_layers=True,depsgraph=depsgraph)
                try:
                    if mesh is not None:total+=write_mesh(out,obj,mesh,axes @ origin @ evaluated.matrix_world,counts)
                finally:evaluated.to_mesh_clear()
            if not counts[2]:out.write('# myengine_empty_layer\n')
        if not total:raise ValueError('No visible triangles in the selected hierarchy')
        return len(groups),total
    return atomic_export(path,write)
