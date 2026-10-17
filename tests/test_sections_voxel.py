from array import array
import math
from types import SimpleNamespace as NS
import unittest
from engine_voxels import VoxelGrid
from engine_voxel_physics import boundary_mesh
from engine_sections import difference_strips
from engine_four_d import slice_layers

def triangle_volume(mesh):
    total=0
    for o in range(0,len(mesh.vertices),24):
        a,b,c=[mesh.vertices[o+j:o+j+3] for j in (0,8,16)]
        total+=(a[0]*(b[1]*c[2]-b[2]*c[1])+a[1]*(b[2]*c[0]-b[0]*c[2])+a[2]*(b[0]*c[1]-b[1]*c[0]))/6
    return total
def rect(x0,y0,x1,y1):return [((x0,y0),(x0,y1)),((x1,y0),(x1,y1))]
def area(p):return abs(sum(p[i][0]*p[(i+1)%len(p)][1]-p[(i+1)%len(p)][0]*p[i][1] for i in range(len(p)))/2)

class SurfaceTests(unittest.TestCase):
    def test_solid_greedy_cube(self):
        g=VoxelGrid((3,4,5),.5)
        for x in range(3):
            for y in range(4):
                for z in range(5):g.set(x,y,z)
        m=boundary_mesh(g);self.assertEqual(len(m.vertices)//24,12)
        self.assertAlmostEqual(triangle_volume(m),3*4*5*.5**3)
    def test_empty_and_hollow(self):
        g=VoxelGrid((3,3,3),1);self.assertIsNone(boundary_mesh(g))
        for x in range(3):
            for y in range(3):
                for z in range(3):
                    if (x,y,z)!=(1,1,1):g.set(x,y,z)
        self.assertAlmostEqual(triangle_volume(boundary_mesh(g)),26)
    def test_caps_close_rotated_solid(self):
        g=VoxelGrid((1,1,1),2);g.set(0,0,0);layers=[NS(geometry=boundary_mesh(g))]
        m=slice_layers(layers,.2,1,(45,0,0),(1,1,1),0)
        expected=4*.2*math.sqrt(2)
        self.assertAlmostEqual(triangle_volume(m),expected,places=5)
        for x in (m.minimum[0],m.maximum[0]):
            self.assertTrue(any(abs(m.vertices[o]-x)<1e-6 and abs(m.vertices[o+3])>.99 for o in range(0,len(m.vertices),8)))
    def test_no_internal_wall_for_same_adjacent_solid(self):
        g=VoxelGrid((1,1,1),2);g.set(0,0,0);layer=NS(geometry=boundary_mesh(g))
        m=slice_layers([layer,layer],.2,1,(45,0,0),(1,1,1),0)
        self.assertAlmostEqual(triangle_volume(m),4*.4*math.sqrt(2),places=5)
        shared=-.1*math.sqrt(2)
        self.assertFalse(any(abs(m.vertices[o]-shared)<1e-6 and abs(m.vertices[o+3])>.99 for o in range(0,len(m.vertices),8)))
    def test_planar_difference_holes_and_overlap(self):
        a=rect(0,0,4,4);b=rect(1,1,3,3)
        pieces=list(difference_strips(a,b));self.assertAlmostEqual(sum(area(p) for owner,p in pieces),12)
        self.assertFalse(list(difference_strips(a,a)))
        pieces=list(difference_strips(rect(0,0,2,2),rect(1,0,3,2)))
        for owner in (0,1):self.assertAlmostEqual(sum(area(p) for who,p in pieces if who==owner),2)
    def test_crossing_contours_split_strips(self):
        a=[((0,0),(2,2)),((4,0),(2,2))];b=rect(1,0,3,2)
        pieces=list(difference_strips(a,b));self.assertAlmostEqual(sum(area(p) for _,p in pieces),2)

if __name__=='__main__':unittest.main()
