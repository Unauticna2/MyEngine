"""OBJ / '+' separated 4D layers / PNG and BMP. Standard library only."""
from __future__ import annotations
from array import array
from dataclasses import dataclass
from pathlib import Path
import math
import json
import re
import struct
import zlib

MAX_BYTES = 64 * 1024 * 1024
MAX_VERTICES = 1_000_000
MAX_TRIANGLES = 1_000_000

@dataclass
class MeshData:
    vertices: array                 # x y z nx ny nz u v, 32 bytes per vertex
    minimum: tuple[float, float, float]
    maximum: tuple[float, float, float]


def asset_path(root: Path, name: str) -> Path:
    """Keep Windows case-insensitive asset names usable by validation on other OSes."""
    p = (root / name).resolve()
    if p.is_file():
        return p
    current = root.resolve()
    for part in Path(name.replace('\\', '/')).parts:
        if part == '..':
            current = current.parent
        elif part not in ('', '.'):
            matches = [c for c in current.iterdir() if c.name.casefold() == part.casefold()]
            if len(matches) != 1:
                raise FileNotFoundError(name)
            current = matches[0]
    if not current.is_file():
        raise FileNotFoundError(name)
    return current.resolve()


def finite(value, limit=1e6):
    f = float(value)
    if not math.isfinite(f) or abs(f) > limit:
        raise ValueError(f'Invalid/out-of-range number: {value!r}')
    return f


def parse_obj(text: str, source='<obj>') -> MeshData:
    xyz, uv, normals = [], [], []
    output = array('f')
    smoothing = None
    sums, pending = {}, []
    lo, hi = [math.inf] * 3, [-math.inf] * 3

    def index(raw, values):
        i = int(raw)
        j = i - 1 if i > 0 else len(values) + i
        if i == 0 or j < 0 or j >= len(values):
            raise ValueError(f'OBJ index {i} outside 1..{len(values)}')
        return j

    for lineno, line in enumerate(text.splitlines(), 1):
        fields = line.partition('#')[0].split()
        if not fields:
            continue
        kind, *data = fields
        try:
            if kind in ('v', 'vn'):
                if len(data) < 3:
                    raise ValueError(f'{kind} requires three coordinates')
                values = tuple(finite(x) for x in data[:3])
                table = xyz if kind == 'v' else normals
                table.append(values)
                if len(table) > MAX_VERTICES:
                    raise ValueError('Too many vertices/normals')
            elif kind == 'vt':
                if not data:
                    raise ValueError('vt requires coordinates')
                uv.append((finite(data[0]), finite(data[1]) if len(data) > 1 else 0.0))
                if len(uv) > MAX_VERTICES * 3:
                    raise ValueError('Too many UV coordinates')
            elif kind == 's':
                if len(data) != 1:
                    raise ValueError('s requires off, on, 0 or a positive group number')
                group = data[0].lower()
                smoothing = None if group in ('off', '0') else (1 if group == 'on' else int(group))
                if smoothing is not None and smoothing <= 0:
                    raise ValueError('Smoothing group must be positive')
            elif kind == 'f':
                if not 3 <= len(data) <= 256:
                    raise ValueError('Face requires 3..256 vertices')
                refs = []
                for ref in data:
                    parts = ref.split('/')
                    if len(parts) > 3 or not parts[0]:
                        raise ValueError('Bad face reference')
                    vi = index(parts[0], xyz)
                    ti = index(parts[1], uv) if len(parts) >= 2 and parts[1] else None
                    ni = index(parts[2], normals) if len(parts) == 3 and parts[2] else None
                    refs.append((vi, ti, ni))
                face_sum = [0.0, 0.0, 0.0]
                used = set()
                for k in range(1, len(refs) - 1):
                    tri = (refs[0], refs[k], refs[k + 1])
                    a, b, c = (xyz[r[0]] for r in tri)
                    u = tuple(b[j] - a[j] for j in range(3))
                    v = tuple(c[j] - a[j] for j in range(3))
                    n = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
                    length = math.sqrt(sum(x*x for x in n))
                    if length <= 1e-12:
                        continue
                    normal = tuple(x / length for x in n)
                    if smoothing is not None:
                        for j in range(3): face_sum[j] += n[j]
                        used.update(r[0] for r in tri)
                    for vi, ti, ni in tri:
                        pos = xyz[vi]
                        vn = normals[ni] if ni is not None else normal
                        nl = math.sqrt(sum(x*x for x in vn))
                        vn = tuple(x/nl for x in vn) if nl > 1e-12 else normal
                        # Simple planar fallback for unwrapped meshes such as the original cube.
                        tex = uv[ti] if ti is not None else (pos[0], pos[2] if abs(normal[1]) > .7 else pos[1])
                        if smoothing is not None and (ni is None or nl <= 1e-12):
                            pending.append((len(output) + 3, (smoothing, vi), vn))
                        output.extend((*pos, *vn, *tex))
                        for j in range(3):
                            lo[j] = min(lo[j], pos[j]); hi[j] = max(hi[j], pos[j])
                    if len(output) // 24 > MAX_TRIANGLES:
                        raise ValueError('Too many triangles')
                if smoothing is not None:
                    # One area vector per polygon/vertex; fan roots must not get extra weight.
                    for vi in used:
                        total = sums.setdefault((smoothing, vi), [0.0, 0.0, 0.0])
                        for j in range(3): total[j] += face_sum[j]
        except (ValueError, IndexError, OverflowError) as exc:
            raise ValueError(f'{source}:{lineno}: {exc}') from exc
    for offset, key, fallback in pending:
        normal = sums[key]
        length = math.sqrt(sum(x*x for x in normal))
        normal = tuple(x/length for x in normal) if length > 1e-12 else fallback
        output[offset:offset+3] = array('f', normal)
    if not output:
        raise ValueError(f'{source}: no non-degenerate triangles')
    return MeshData(output, tuple(lo), tuple(hi))


def four_d_metadata(text):
    for line in text.splitlines()[:32]:
        if line.startswith('# myengine4d '):
            value=json.loads(line[len('# myengine4d '):])
            if not isinstance(value,dict) or value.get('format')!=1:raise ValueError('Unsupported myengine4d header')
            spacing=finite(value.get('layerSpacing',.1))
            if spacing<=0:raise ValueError('4D layerSpacing must be positive')
            return {'layerSpacing':spacing}
    return {}

def four_d_spacing(path,default=.1):
    with Path(path).open(encoding='utf-8-sig') as file:text=file.read(65536)
    return four_d_metadata(text).get('layerSpacing',default)

def load_layers(path: Path) -> list[MeshData]:
    if path.stat().st_size > MAX_BYTES:
        raise ValueError(f'Asset exceeds {MAX_BYTES // 1024**2} MiB: {path}')
    text = path.read_text(encoding='utf-8-sig')
    if path.suffix.lower() != '.4d':
        return [parse_obj(text, str(path))]
    blocks = re.split(r'(?m)^[ \t]*\+[ \t]*\r?$', text)
    if blocks and not blocks[-1].strip():
        blocks.pop()               # The user's format has a trailing '+' terminator.
    if not blocks or len(blocks) > 256 or any(not b.strip() for b in blocks):
        raise ValueError(f'{path}: expected 1..256 nonempty OBJ layers separated by +')
    metadata=four_d_metadata(text);result=[]
    for i,block in enumerate(blocks):
        empty=any(line.strip()=='# myengine_empty_layer' for line in block.splitlines())
        if empty:
            if any(line.partition('#')[0].strip() for line in block.splitlines()):raise ValueError('Empty layer contains OBJ records')
            mesh=MeshData(array('f'),(0,0,0),(0,0,0))
        else:mesh=parse_obj(block,f'{path} [layer {i}]')
        if 'layerSpacing' in metadata:mesh.layer_spacing=metadata['layerSpacing']
        result.append(mesh)
    if not any(mesh.vertices for mesh in result):raise ValueError('4D file has no geometry')
    return result


def slice_index(camera_w: float, object_w: float, spacing: float, count: int):
    """Nearest layer; half-open cells [w-step/2, w+step/2). No end clamping."""
    if not math.isfinite(spacing) or spacing <= 0:
        raise ValueError('layerSpacing must be positive')
    relative = (camera_w - object_w) / spacing
    i = math.floor(relative + 0.5 + 1e-7)
    return i if 0 <= i < count else None


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p-a), abs(p-b), abs(p-c)
    return a if pa <= pb and pa <= pc else b if pb <= pc else c


def decode_png(blob: bytes):
    if blob[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('Bad PNG signature')
    pos, compressed, palette, alpha = 8, bytearray(), b'', b''
    header = None
    while pos + 12 <= len(blob):
        size, = struct.unpack_from('>I', blob, pos)
        kind = blob[pos+4:pos+8]
        end = pos + 12 + size
        if end > len(blob):
            raise ValueError('Truncated PNG chunk')
        payload = blob[pos+8:pos+8+size]
        crc, = struct.unpack_from('>I', blob, pos+8+size)
        if zlib.crc32(kind+payload) & 0xffffffff != crc:
            raise ValueError('PNG CRC mismatch')
        if kind == b'IHDR':
            header = struct.unpack('>IIBBBBB', payload)
        elif kind == b'IDAT':
            compressed.extend(payload)
        elif kind == b'PLTE':
            palette = payload
        elif kind == b'tRNS':
            alpha = payload
        elif kind == b'IEND':
            break
        pos = end
    if header is None:
        raise ValueError('PNG has no IHDR')
    w, h, depth, color, compression, filtering, interlace = header
    channels = {0:1, 2:3, 3:1, 4:2, 6:4}.get(color)
    if not (1 <= w <= 4096 and 1 <= h <= 4096):
        raise ValueError('Texture dimensions must be 1..4096')
    if depth != 8 or channels is None or compression or filtering or interlace:
        raise ValueError('Use an 8-bit non-interlaced PNG (RGB/RGBA/gray/palette)')
    stride = w * channels
    expected = h * (stride + 1)
    decoder = zlib.decompressobj()
    raw = decoder.decompress(compressed, expected+1)
    if len(raw) != expected or not decoder.eof:
        raise ValueError('Invalid PNG decompressed size')
    from engine_ui_native import png_pixels
    accelerated=png_pixels(raw,w,h,color,palette,alpha)
    if accelerated is not None:return w,h,accelerated
    rgba = bytearray(w*h*4)
    previous = bytearray(stride)
    for y in range(h):
        begin = y*(stride+1)
        mode = raw[begin]
        row = bytearray(raw[begin+1:begin+1+stride])
        if mode > 4:
            raise ValueError('Invalid PNG filter')
        for x in range(stride):
            a = row[x-channels] if x >= channels else 0
            b = previous[x]
            c = previous[x-channels] if x >= channels else 0
            if mode == 1: row[x] = (row[x]+a)&255
            elif mode == 2: row[x] = (row[x]+b)&255
            elif mode == 3: row[x] = (row[x]+((a+b)//2))&255
            elif mode == 4: row[x] = (row[x]+_paeth(a,b,c))&255
        for x in range(w):
            off = x*channels
            if color == 6: pixel = row[off:off+4]
            elif color == 2:
                rgb = row[off:off+3]
                transparent = len(alpha)==6 and tuple(rgb)==struct.unpack('>HHH',alpha)
                pixel = bytes(rgb)+bytes([0 if transparent else 255])
            elif color == 0:
                g = row[off]
                transparent = len(alpha)==2 and g==struct.unpack('>H',alpha)[0]
                pixel = bytes((g,g,g,0 if transparent else 255))
            elif color == 4:
                g,a = row[off:off+2]; pixel=bytes((g,g,g,a))
            else:
                i=row[off]
                if i*3+3>len(palette):raise ValueError('PNG palette index out of bounds')
                pixel=palette[i*3:i*3+3]+bytes([alpha[i] if i<len(alpha) else 255])
            dest=((h-1-y)*w+x)*4     # OpenGL upload orientation: bottom row first.
            rgba[dest:dest+4]=pixel
        previous=row
    return w,h,bytes(rgba)


def decode_bmp(blob: bytes):
    if len(blob)<54 or blob[:2]!=b'BM':raise ValueError('Bad BMP')
    offset,=struct.unpack_from('<I',blob,10)
    header,=struct.unpack_from('<I',blob,14)
    w,h,planes,bpp,compression=struct.unpack_from('<iiHHI',blob,18)
    if header<40 or planes!=1 or compression!=0 or bpp not in (24,32):
        raise ValueError('Use uncompressed 24-bit or 32-bit BMP')
    if not (1<=w<=4096 and 1<=abs(h)<=4096):raise ValueError('Invalid BMP dimensions')
    stride=((w*bpp+31)//32)*4
    height=abs(h)
    if offset+height*stride>len(blob):raise ValueError('Truncated BMP pixels')
    out=bytearray(w*height*4)
    for y in range(height):
        sy=y if h>0 else height-1-y
        for x in range(w):
            p=offset+sy*stride+x*(bpp//8);b,g,r=blob[p:p+3]
            # BI_RGB 32-bit alpha is undefined; treat it as opaque.
            out[(y*w+x)*4:(y*w+x)*4+4]=bytes((r,g,b,255))
    return w,height,bytes(out)


def load_texture(path: Path):
    if path.stat().st_size>MAX_BYTES:raise ValueError('Texture file is too large')
    data=path.read_bytes()
    if path.suffix.lower()=='.png':w,h,rgba=decode_png(data)
    elif path.suffix.lower()=='.bmp':w,h,rgba=decode_bmp(data)
    else:raise ValueError('Textures: use PNG or BMP')
    # Keep compatibility with Windows' baseline OpenGL 1.1 implementation.
    nw,nh=1<<(w-1).bit_length(),1<<(h-1).bit_length()
    if (nw,nh)!=(w,h):
        from engine_ui_native import resize_rgba
        accelerated=resize_rgba(rgba,w,h,nw,nh)
        if accelerated is not None:return nw,nh,accelerated
        out=bytearray(nw*nh*4)
        for y in range(nh):
            sy=y*h//nh
            for x in range(nw):
                sx=x*w//nw;p=(sy*w+sx)*4;q=(y*nw+x)*4
                out[q:q+4]=rgba[p:p+4]
        rgba=bytes(out);w,h=nw,nh
    return w,h,rgba
