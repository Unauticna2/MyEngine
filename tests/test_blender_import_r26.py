"""Parser, mesh mapping and rollback tests; fake bpy, not an actual Blender run."""
import importlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import patch
from engine_assets import load_layers
from test_blender_export_r26 import Vec

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'r26_import_test'
package = ModuleType(PACKAGE)
package.__path__ = [str(ROOT / 'addons/myengine_4d')]
sys.modules[PACKAGE] = package
fmt = importlib.import_module(PACKAGE + '.format4d')
importer = importlib.import_module(PACKAGE + '.importer')
exporter = importlib.import_module(PACKAGE + '.exporter')
hierarchy = importlib.import_module(PACKAGE + '.hierarchy')

TRI = '''o Test
v 0 2 3
v 1 2 3
v 0 3 3
vt 0 0
vt 1 0
vt 0 1
vn 0 0 1
f 1/1/1 2/2/1 3/3/1
'''


class Mesh:
    def __init__(self, name):
        self.name, self.users = name, 0
        self.uv_layers = NS(active=None, new=self.new_uv)
        self.use_auto_smooth = False

    def from_pydata(self, vertices, edges, faces):
        self.vertices = [NS(co=Vec(v), normal=Vec([0, 0, 1])) for v in vertices]
        self.polygons, self.loops, self.loop_triangles = [], [], []
        for face in faces:
            indices = tuple(range(len(self.loops), len(self.loops) + len(face)))
            self.polygons.append(NS(loop_indices=indices, use_smooth=False, normal=Vec([0, 0, 1])))
            self.loops.extend(NS(index=i, vertex_index=vi, normal=Vec([0, 0, 1])) for i, vi in zip(indices, face))
            self.loop_triangles.extend(NS(loops=(indices[0], indices[i], indices[i+1])) for i in range(1, len(indices)-1))

    def new_uv(self, **kwargs):
        self.uv_layers.active = NS(data=[NS(uv=(0, 0)) for _ in self.loops])
        return self.uv_layers.active

    def update(self, **kwargs): pass
    def calc_loop_triangles(self): pass
    def calc_normals_split(self): pass
    def normals_split_custom_set(self, normals):
        assert len(normals) == len(self.loops)
        for loop, normal in zip(self.loops, normals):
            loop.normal = Vec(normal)


class Object(dict):
    def __init__(self, name, data):
        self.name, self.data = name, data
        self.type = 'MESH' if data is not None else 'EMPTY'
        self.children = []
        self._parent, self.selected = None, False
        if data is not None: data.users += 1
    @property
    def parent(self): return self._parent
    @parent.setter
    def parent(self, obj):
        self._parent = obj
        obj.children.append(self)
    def select_set(self, value): self.selected = value


class Store:
    def __init__(self, factory): self.factory, self.items = factory, []
    def new(self, *args):
        item = self.factory(*args)
        self.items.append(item)
        return item
    def remove(self, item, **kwargs):
        self.items = [v for v in self.items if v is not item]
        if isinstance(item, Object) and item.data is not None: item.data.users -= 1


def environment():
    bpy = NS(data=NS(meshes=Store(Mesh), objects=Store(Object),
                    collections=Store(lambda name: NS(name=name, objects=NS(link=lambda obj: None)))))
    old = bpy.data.objects.new('Existing object', None)
    old.select_set(True)
    context = NS(mode='OBJECT', selected_objects=[old],
                 view_layer=NS(objects=NS(active=old)),
                 scene=NS(collection=NS(children=NS(link=lambda c: None)),
                          myengine4d_spacing=.8, myengine4d_root_mode='ROOT'))
    return bpy, context, old


class EngineAxes:
    def to_3x3(self): return self
    def determinant(self): return 1
    def inverted(self): return self
    def transposed(self): return self
    def __matmul__(self, value):
        x, y, z = value
        return Vec((x, z, -y))


class ImportTests(unittest.TestCase):
    def test_metadata_empty_layers_axes_uv_and_normals(self):
        document = fmt.parse_4d(hierarchy.header(.25, 'ROOT') + TRI + '+\n# myengine_empty_layer\n+\n' + TRI)
        self.assertEqual(document.spacing, .25)
        self.assertEqual(len(document.layers), 3)
        self.assertFalse(document.layers[1].faces)
        mesh = Mesh('Test')
        importer.fill_mesh(mesh, document.layers[0])
        self.assertEqual(tuple(mesh.vertices[0].co), (0, -3, 2))
        self.assertEqual(mesh.uv_layers.active.data[1].uv, (1, 0))
        self.assertEqual(tuple(mesh.loops[0].normal), (0, -1, 0))
        self.assertTrue(mesh.use_auto_smooth)

    def test_negative_indices_and_legacy_terminator(self):
        data = TRI.replace('f 1/1/1 2/2/1 3/3/1', 'f -3/-3/-1 -2/-2/-1 -1/-1/-1')
        document = fmt.parse_4d('\ufeff' + data + '+\r\n')
        self.assertEqual(document.spacing, .1)
        self.assertEqual(document.layers[0].faces[0], [(0, 0, 0), (1, 1, 0), (2, 2, 0)])

    def test_obj_indices_restart_for_each_layer(self):
        doc = fmt.parse_4d(TRI + '+\n' + TRI)
        self.assertEqual(doc.layers[0].faces, doc.layers[1].faces)
        with self.assertRaisesRegex(ValueError, 'index'):
            fmt.parse_4d(TRI + '+\nf 1 2 3\n')

    def test_uv_seam_keeps_distinct_loop_coordinates(self):
        doc = fmt.parse_4d(TRI + 'vt .4 .5\nf 1/4/1 3/3/1 2/2/1\n')
        mesh = Mesh('UV')
        importer.fill_mesh(mesh, doc.layers[0])
        self.assertEqual(mesh.loops[0].vertex_index, mesh.loops[3].vertex_index)
        self.assertEqual(mesh.uv_layers.active.data[0].uv, (0, 0))
        self.assertEqual(mesh.uv_layers.active.data[3].uv, (.4, .5))

    def test_absent_uv_and_normals_and_mixed_face_references(self):
        doc = fmt.parse_4d('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n')
        mesh = Mesh('Plain')
        importer.fill_mesh(mesh, doc.layers[0])
        self.assertIsNone(mesh.uv_layers.active)
        self.assertFalse(mesh.polygons[0].use_smooth)
        self.assertEqual(tuple(mesh.loops[0].normal), (0, -1, 0))
        mixed = fmt.parse_4d(TRI.replace('1/1/1 2/2/1 3/3/1', '1//1 2/2 3'))
        importer.fill_mesh(mesh, mixed.layers[0])
        self.assertEqual(mesh.uv_layers.active.data[0].uv, (0, 0))
        self.assertEqual(mesh.uv_layers.active.data[1].uv, (1, 0))

    def test_smoothing_groups_are_kept_separate_without_explicit_normals(self):
        base = 'v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\ns 1\nf 1 2 3\n'
        same = fmt.split_normals_for_layer(fmt.parse_4d(base + 's 1\nf 1 4 2\n').layers[0])
        different = fmt.split_normals_for_layer(fmt.parse_4d(base + 's 2\nf 1 4 2\n').layers[0])
        self.assertEqual(same[0], same[3])
        self.assertNotEqual(different[0], different[3])
        self.assertEqual(different[0], (0, -1, 0))

    def test_real_existing_engine_asset(self):
        path = ROOT / 'assets/spherecube.4d'
        doc = fmt.read_4d(path)
        expected = load_layers(path)
        self.assertEqual(len(doc.layers), len(expected))
        for layer, geometry in zip(doc.layers, expected):
            self.assertEqual(sum(len(face) - 2 for face in layer.faces), len(geometry.vertices) // 24)

    def test_chain_has_exact_W_depth_and_keeps_existing_scene(self):
        doc = fmt.parse_4d(hierarchy.header(.23, 'ROOT') + '# myengine_empty_layer\n+\n' + TRI + '+\n# myengine_empty_layer\n')
        bpy, ctx, old = environment()
        root = importer.import_document(ctx, doc, 'Example', bpy)
        groups = hierarchy.group_layers(root, 'CHILDREN')
        self.assertEqual([group[0].type for group in groups], ['EMPTY', 'MESH', 'EMPTY'])
        self.assertEqual([group[0]['myengine4d_layer'] for group in groups], [0, 1, 2])
        self.assertIs(ctx.view_layer.objects.active, root)
        self.assertFalse(old.selected)
        self.assertTrue(any(obj is old for obj in bpy.data.objects.items))
        self.assertEqual(root['myengine4d_spacing'], .23)
        self.assertEqual(ctx.scene.myengine4d_root_mode, 'CHILDREN')

    def test_import_export_roundtrip_readable_by_actual_engine(self):
        text = hierarchy.header(.25, 'ROOT') + TRI + '+\n# myengine_empty_layer\n+\n' + TRI
        bpy, ctx, _ = environment()
        root = importer.import_document(ctx, fmt.parse_4d(text), 'Test', bpy)
        stream = io.StringIO()
        stream.write(hierarchy.header(root['myengine4d_spacing'], 'CHILDREN'))
        for i, group in enumerate(hierarchy.group_layers(root, 'CHILDREN')):
            if i: stream.write('+\n')
            obj = group[0]
            if obj.data is None: stream.write('# myengine_empty_layer\n')
            else: exporter.write_mesh(stream, obj, obj.data, EngineAxes(), [0, 0, 0])
        with tempfile.TemporaryDirectory() as directory:
            a, b = (Path(directory) / name for name in ('original.4d', 'roundtrip.4d'))
            a.write_text(text); b.write_text(stream.getvalue())
            for before, after in zip(load_layers(a), load_layers(b)):
                self.assertEqual(list(before.vertices), list(after.vertices))
                self.assertEqual(after.layer_spacing, .25)

    def test_mesh_creation_error_rolls_back_only_its_own_resources(self):
        bpy, ctx, old = environment()
        with patch.object(importer, 'fill_mesh', side_effect=RuntimeError('test failure')):
            with self.assertRaisesRegex(RuntimeError, 'test failure'):
                importer.import_document(ctx, fmt.parse_4d(TRI), 'Bad', bpy)
        self.assertEqual(len(bpy.data.objects.items), 1)
        self.assertIs(bpy.data.objects.items[0], old)
        self.assertEqual(bpy.data.meshes.items, [])
        self.assertEqual(bpy.data.collections.items, [])
        self.assertIs(ctx.view_layer.objects.active, old)
        self.assertTrue(old.selected)
        self.assertEqual(ctx.scene.myengine4d_spacing, .8)

    def test_rejects_invalid_indices_numbers_and_empty_blocks(self):
        for text in [TRI.replace('f 1/1/1', 'f 0/1/1'), TRI.replace('f 1/1/1', 'f 4/1/1'),
                     TRI.replace('v 0 2 3', 'v nan 2 3'), TRI.replace('v 0 2 3', 'v 1e30 2 3'),
                     TRI + '+\n+\n' + TRI, '# myengine_empty_layer\n' + TRI,
                     '# myengine_empty_layer\n', TRI.replace('f 1/1/1 2/2/1', 'f 1 1')]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                fmt.parse_4d(text)

    def test_header_and_file_limits(self):
        for metadata in ['{"format":2}', '{"format":1,"layerSpacing":0}',
                         '{"format":1,"axes":"unknown"}', '[]', '{broken']:
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                fmt.parse_4d('# myengine4d ' + metadata + '\n' + TRI)
        with self.assertRaises(ValueError): fmt.parse_4d('+\n'.join([TRI] * 257))
        with patch.object(fmt, 'MAX_BYTES', 10):
            with self.assertRaises(ValueError): fmt.parse_4d(TRI)

    def test_import_menu_registration_and_unregister(self):
        bpy = ModuleType('bpy'); props = ModuleType('bpy.props')
        extras = ModuleType('bpy_extras'); utils = ModuleType('bpy_extras.io_utils')
        imported, exported, classes = [], [], []
        bpy.types = NS(Operator=type('Operator', (), {}), Panel=type('Panel', (), {}),
                       Scene=type('Scene', (), {}),
                       TOPBAR_MT_file_import=imported, TOPBAR_MT_file_export=exported)
        bpy.utils = NS(register_class=classes.append, unregister_class=classes.remove)
        for prop in ('BoolProperty', 'EnumProperty', 'FloatProperty', 'StringProperty'):
            setattr(props, prop, lambda **kw: None)
        utils.ExportHelper = type('ExportHelper', (), {})
        utils.ImportHelper = type('ImportHelper', (), {})
        path = ROOT / 'addons/myengine_4d/__init__.py'
        spec = importlib.util.spec_from_file_location(PACKAGE, path, submodule_search_locations=[str(path.parent)])
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {PACKAGE: module, 'bpy': bpy, 'bpy.props': props,
                                      'bpy_extras': extras, 'bpy_extras.io_utils': utils}):
            spec.loader.exec_module(module)
            module.register()
            self.assertEqual(module.bl_info['version'], (1, 1, 0))
            self.assertIn(module.MYENGINE_OT_import_4d, classes)
            operators = []
            menu = NS(layout=NS(operator=lambda identifier, **kw: operators.append(identifier)))
            imported[0](menu, None)
            self.assertEqual(operators, ['import_scene.myengine_4d'])
            module.unregister()
            self.assertEqual((classes, imported, exported), ([], [], []))


if __name__ == '__main__': unittest.main()
