"""Read the engine's '+' separated OBJ layers without importing bpy."""
from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import re
from .hierarchy import MAX_BYTES, MAX_LAYERS

MAX_ITEMS = 1_000_000


@dataclass
class Layer:
    vertices: list = field(default_factory=list)
    uv: list = field(default_factory=list)
    normals: list = field(default_factory=list)
    faces: list = field(default_factory=list)  # per corner: (vertex, uv|None, normal|None)
    smoothing: list = field(default_factory=list)
    name: str = ''


@dataclass
class Document:
    layers: list
    spacing: float = .1


def finite(value):
    number = float(value)
    if not math.isfinite(number) or abs(number) > 1e6:
        raise ValueError('Non-finite / oversized coordinate')
    return number


def obj_index(text, table):
    raw = int(text)
    index = raw - 1 if raw > 0 else len(table) + raw
    if raw == 0 or not 0 <= index < len(table):
        raise ValueError('OBJ index %s outside 1..%s' % (raw, len(table)))
    return index


def parse_layer(block, source, offset):
    layer = Layer()
    lines = block.splitlines()
    if any(line.strip() == '# myengine_empty_layer' for line in lines):
        if any(line.partition('#')[0].strip() for line in lines):
            raise ValueError(source + ': empty layer contains OBJ records')
        return layer
    smoothing = None
    triangles = 0
    for lineno, line in enumerate(lines, offset + 1):
        fields = line.partition('#')[0].split()
        if not fields:
            continue
        kind, *data = fields
        try:
            if kind in ('v', 'vn'):
                if len(data) < 3:
                    raise ValueError(kind + ' requires three coordinates')
                table = layer.vertices if kind == 'v' else layer.normals
                table.append(tuple(finite(x) for x in data[:3]))
                if len(table) > MAX_ITEMS:
                    raise ValueError('Too many vertices / normals')
            elif kind == 'vt':
                if not data:
                    raise ValueError('vt requires coordinates')
                layer.uv.append((finite(data[0]), finite(data[1]) if len(data) > 1 else 0.))
                if len(layer.uv) > MAX_ITEMS * 3:
                    raise ValueError('Too many UV coordinates')
            elif kind == 's':
                if len(data) != 1:
                    raise ValueError('s requires off, on, 0 or a positive group number')
                group = data[0].lower()
                smoothing = None if group in ('off', '0') else (1 if group == 'on' else int(group))
                if smoothing is not None and smoothing <= 0:
                    raise ValueError('Smoothing group must be positive')
            elif kind == 'o' and not layer.name:
                layer.name = ' '.join(data)
            elif kind == 'f':
                if not 3 <= len(data) <= 256:
                    raise ValueError('Face requires 3..256 vertices')
                refs = []
                for ref in data:
                    parts = ref.split('/')
                    if len(parts) > 3 or not parts[0]:
                        raise ValueError('Bad face reference')
                    vi = obj_index(parts[0], layer.vertices)
                    ti = obj_index(parts[1], layer.uv) if len(parts) > 1 and parts[1] else None
                    ni = obj_index(parts[2], layer.normals) if len(parts) > 2 and parts[2] else None
                    refs.append((vi, ti, ni))
                if len({r[0] for r in refs}) != len(refs):
                    raise ValueError('Face repeats a vertex')
                triangles += len(refs) - 2
                if triangles > MAX_ITEMS:
                    raise ValueError('Too many triangles in a layer')
                layer.faces.append(refs)
                layer.smoothing.append(smoothing)
            # OBJ object/group names and material references are not executable.
            # This format does not embed MTL files or image data.
        except (ValueError, OverflowError) as exc:
            raise ValueError('%s:%s: %s' % (source, lineno, exc)) from exc
    if not layer.faces:
        raise ValueError(source + ': layer has no faces (use # myengine_empty_layer for a gap)')
    return layer


def parse_4d(text, source='<4d>'):
    if len(text.encode('utf-8')) > MAX_BYTES:
        raise ValueError('4D file exceeds 64 MiB')
    text = text.lstrip('\ufeff')
    spacing = .1
    for line in text.splitlines()[:32]:
        if line.startswith('# myengine4d '):
            try:
                metadata = json.loads(line[len('# myengine4d '):])
                if not isinstance(metadata, dict) or metadata.get('format') != 1:
                    raise ValueError('Unsupported myengine4d header')
                if metadata.get('axes', 'X,Z,-Y') != 'X,Z,-Y':
                    raise ValueError('Unsupported coordinate axes')
                spacing = finite(metadata.get('layerSpacing', .1))
                if spacing <= 0:
                    raise ValueError('W layer spacing must be positive')
            except (ValueError, TypeError) as exc:
                raise ValueError(source + ': invalid 4D header: ' + str(exc)) from exc
            break
    blocks = re.split(r'(?m)^[ \t]*\+[ \t]*\r?$', text)
    if blocks and not blocks[-1].strip():
        blocks.pop()  # Legacy files may end with a '+' terminator.
    if not blocks or len(blocks) > MAX_LAYERS or any(not b.strip() for b in blocks):
        raise ValueError(source + ': expected 1..256 OBJ layers separated by +')
    layers = []
    for i, block in enumerate(blocks):
        layers.append(parse_layer(block, '%s [layer %s]' % (source, i), 0))
    if not any(layer.faces for layer in layers):
        raise ValueError(source + ': 4D file has no geometry')
    return Document(layers, spacing)


def read_4d(path):
    path = Path(path)
    with path.open('rb') as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('4D file exceeds 64 MiB')
    return parse_4d(data.decode('utf-8-sig'), str(path))


def to_blender(vector):
    """Inverse of exporter's (X,Y,Z) -> (X,Z,-Y), for positions and normals."""
    x, y, z = vector
    return (x, -z, y)


def split_normals_for_layer(layer):
    """Keep explicit vn; calculate area-weighted OBJ smoothing groups otherwise."""
    sums = {}
    face_normals = []
    for refs, group in zip(layer.faces, layer.smoothing):
        a = layer.vertices[refs[0][0]]
        total = [0., 0., 0.]
        for i in range(1, len(refs) - 1):
            b, c = (layer.vertices[refs[j][0]] for j in (i, i + 1))
            u, v = ([p - q for p, q in zip(vertex, a)] for vertex in (b, c))
            cross = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
            for j in range(3):
                total[j] += cross[j]
        face_normals.append(total)
        if group is not None:
            for vi, _, _ in refs:
                value = sums.setdefault((group, vi), [0., 0., 0.])
                for j in range(3):
                    value[j] += total[j]
    result = []
    for refs, group, face_normal in zip(layer.faces, layer.smoothing, face_normals):
        for vi, _, ni in refs:
            n = layer.normals[ni] if ni is not None else (0., 0., 0.)
            if sum(x*x for x in n) < 1e-24:
                n = sums[(group, vi)] if group is not None else face_normal
            length = math.sqrt(sum(x*x for x in n))
            if length < 1e-12:
                n = face_normal
                length = math.sqrt(sum(x*x for x in n))
            result.append(to_blender(tuple(x/length for x in n)) if length else (0., 0., 0.))
    return result
