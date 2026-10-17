import math
import struct
import tempfile
import unittest
from array import array
from pathlib import Path
from types import SimpleNamespace as NS
from engine_magica import VoxFile,default_palette,rotation
from engine_assets import MeshData
from engine_four_d import slice_layers,rotation4,transform

def integer(n):return struct.pack('<i',n)
def dictionary(d):
    return integer(len(d))+b''.join(integer(len(k.encode()))+k.encode()+integer(len(v.encode()))+v.encode() for k,v in d.items())
def chunk(tag,data):return tag+struct.pack('<II',len(data),0)+data
def model(size,cells):return chunk(b'SIZE',struct.pack('<iii',*size))+chunk(b'XYZI',integer(len(cells))+bytes(v for c in cells for v in c))
def container(data):return b'VOX '+integer(150)+b'MAIN'+struct.pack('<II',0,len(data))+data
def tr(id,child,t='0 0 0',r='4'):return chunk(b'nTRN',integer(id)+dictionary({})+integer(child)+integer(-1)+integer(-1)+integer(1)+dictionary({'_t':t,'_r':r}))
def shape(id,modelid):return chunk(b'nSHP',integer(id)+dictionary({})+integer(1)+integer(modelid)+dictionary({}))

class VoxTests(unittest.TestCase):
    def load(self,data):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'fixture.vox';p.write_bytes(data);return VoxFile(p)
    def test_palette_and_axis_conversion(self):
        rgba=bytes((i,j,255-i,255)[k] for i in range(256) for j in [17] for k in range(4))
        v=self.load(container(model((2,3,4),[(1,0,3,1),(0,2,0,255)])+chunk(b'RGBA',rgba)))
        g=v.grid(.25);self.assertEqual(g.size,(2,4,3));self.assertEqual(g.cell_size,.25)
        def pixel(x,y,z):
            i=(x+g.size[0]*(y+g.size[1]*z))*4;return tuple(g.pixels[i:i+4])
        self.assertEqual(pixel(1,3,2),(0,17,255,255))
        self.assertEqual(pixel(0,0,0),(254,17,1,255))
        self.assertEqual(sum(a>0 for a in g.pixels[3::4]),2)
    def test_default_palette(self):
        p=default_palette();self.assertEqual(len(p),256);self.assertEqual(p[1],(255,255,255,255))
        self.assertEqual(p[216],(238,0,0,255));self.assertEqual(p[255],(17,17,17,255))
        self.assertEqual(rotation(4),((1,0,0),(0,1,0),(0,0,1)))
    def test_instances_rotation_and_model_selection(self):
        m=model((2,1,1),[(0,0,0,1),(1,0,0,2)])
        group=chunk(b'nGRP',integer(0)+dictionary({})+integer(2)+integer(1)+integer(3))
        v=self.load(container(m+group+tr(1,2)+shape(2,0)+tr(3,4,'3 0 0','17')+shape(4,0)))
        g=v.grid();self.assertEqual(g.size,(4,1,2));self.assertEqual(sum(a>0 for a in g.pixels[3::4]),4)
        self.assertEqual(tuple(g.pixels[(3+4*1)*4:(3+4*1)*4+4]),v.palette[1])
        self.assertEqual(v.grid(model_index=0).size,(2,1,1))
        with self.assertRaises(ValueError):v.grid(model_index=1)
    def test_reject_bad_or_truncated_data(self):
        good=container(model((1,1,1),[(0,0,0,1)]))
        for data in (good[:-1],b'not vox',container(model((1,1,1),[(1,0,0,1)])),container(chunk(b'XYZI',integer(0)))):
            with self.assertRaises(ValueError):self.load(data)
    def test_cycle_rejected(self):
        v=self.load(container(model((1,1,1),[(0,0,0,1)])+tr(0,0)))
        with self.assertRaises(ValueError):v.grid()
    def test_user_model(self):
        g=VoxFile(Path(__file__).resolve().parent.parent/'assets/vox.vox').grid()
        self.assertEqual(g.size,(40,40,40));self.assertEqual(sum(a>0 for a in g.pixels[3::4]),8127)

class FourDTests(unittest.TestCase):
    def layers(self):
        vertices=array('f')
        for p in ((0,0,0),(1,0,0),(0,1,0)):vertices.extend((*p,0,0,1,*p[:2]))
        return [NS(geometry=MeshData(vertices,(0,0,0),(1,1,0)))]
    def test_rotation_orthogonal_and_preserves_norm(self):
        m=rotation4((20,-38,72));v=(2,3,-5,7);r=transform(m,v)
        self.assertAlmostEqual(sum(x*x for x in v),sum(x*x for x in r))
        for a in range(4):
            for b in range(4):self.assertAlmostEqual(sum(m[a][k]*m[b][k] for k in range(4)),float(a==b))
    def test_identity_slice_and_w_range(self):
        layers=self.layers();mesh=slice_layers(layers,.1,1,(0,0,0),(1,1,1),0)
        self.assertEqual(len(mesh.vertices),24);self.assertEqual(mesh.minimum,(0,0,0));self.assertEqual(mesh.maximum,(1,1,0))
        self.assertIsNone(slice_layers(layers,.1,1,(0,0,0),(1,1,1),.06))
        self.assertIsNotNone(slice_layers(layers,.1,2,(0,0,0),(1,1,1),.06))
    def test_xw_quarter_turn_changes_geometry(self):
        # X becomes W, so the cut W=.5 crosses the original triangle at X=.5.
        mesh=slice_layers(self.layers(),.2,1,(90,0,0),(1,1,1),.5)
        self.assertIsNotNone(mesh)
        self.assertAlmostEqual(mesh.minimum[0],-.1,places=6);self.assertAlmostEqual(mesh.maximum[0],.1,places=6)
        self.assertAlmostEqual(mesh.minimum[1],0);self.assertAlmostEqual(mesh.maximum[1],.5)
        for value in mesh.vertices:self.assertTrue(math.isfinite(value))

if __name__=='__main__':unittest.main()
