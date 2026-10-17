"""Create editable Blender meshes, one object per W layer; bpy stays on its main thread."""
from pathlib import Path
from .format4d import read_4d, to_blender, split_normals_for_layer


def fill_mesh(mesh, layer):
    mesh.from_pydata([to_blender(v) for v in layer.vertices], [],
                     [[ref[0] for ref in face] for face in layer.faces])
    mesh.update(calc_edges=True)
    # Keep topology and loop order intact: UV and custom normals are per corner.
    if len(mesh.polygons) != len(layer.faces):
        raise ValueError('Blender changed the imported face topology')
    uv = mesh.uv_layers.new(name='UVMap') if layer.uv else None
    for polygon, refs, group in zip(mesh.polygons, layer.faces, layer.smoothing):
        if len(polygon.loop_indices) != len(refs):
            raise ValueError('Blender changed the imported corner topology')
        polygon.use_smooth = group is not None or any(ref[2] is not None for ref in refs)
        if uv:
            for li, (_, ti, _) in zip(polygon.loop_indices, refs):
                uv.data[li].uv = layer.uv[ti] if ti is not None else (0., 0.)
    # Blender 3.1 needs Auto Smooth for custom split normals. In 4.1+ it is gone.
    if hasattr(mesh, 'use_auto_smooth'):
        mesh.use_auto_smooth = True
    mesh.normals_split_custom_set(split_normals_for_layer(layer))
    mesh.update()


def import_document(context, document, name, bpy):
    """Build a canonical chain; roll back only newly created datablocks on failure."""
    objects, meshes = [], []
    collection = None
    old_selection = list(context.selected_objects)
    old_active = context.view_layer.objects.active
    old_spacing = context.scene.myengine4d_spacing
    old_mode = context.scene.myengine4d_root_mode
    try:
        collection = bpy.data.collections.new(name + ' 4D')
        context.scene.collection.children.link(collection)
        root = bpy.data.objects.new(name, None)
        objects.append(root)
        collection.objects.link(root)
        root.empty_display_type = 'PLAIN_AXES'
        root['myengine4d_imported'] = True
        root['myengine4d_spacing'] = document.spacing
        parent = root
        for index, layer in enumerate(document.layers):
            label = '%s_W%03d' % (name, index)
            mesh = None
            if layer.faces:
                mesh = bpy.data.meshes.new(label)
                meshes.append(mesh)
                fill_mesh(mesh, layer)
            obj = bpy.data.objects.new(label, mesh)
            objects.append(obj)
            collection.objects.link(obj)
            obj.parent = parent
            # All transforms remain identity. W is hierarchy depth, not a Z offset.
            obj['myengine4d_layer'] = index
            obj['myengine4d_w'] = index * document.spacing
            if mesh is None:
                obj.empty_display_type = 'PLAIN_AXES'
            parent = obj
        context.scene.myengine4d_spacing = document.spacing
        context.scene.myengine4d_root_mode = 'CHILDREN'
        for obj in old_selection:
            obj.select_set(False)
        for obj in objects:
            obj.select_set(True)
        context.view_layer.objects.active = root
        return root
    except Exception:
        for obj in reversed(objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        for mesh in meshes:
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        if collection is not None:
            bpy.data.collections.remove(collection, do_unlink=True)
        context.scene.myengine4d_spacing = old_spacing
        context.scene.myengine4d_root_mode = old_mode
        for obj in old_selection:
            obj.select_set(True)
        context.view_layer.objects.active = old_active
        raise


def import_4d(context, path):
    import bpy
    if context.mode != 'OBJECT':
        raise ValueError('Switch to Object Mode before importing')
    document = read_4d(path)  # Validate the entire file before changing the scene.
    root = import_document(context, document, Path(path).stem, bpy)
    triangles = sum(len(face) - 2 for layer in document.layers for face in layer.faces)
    return root, len(document.layers), triangles
