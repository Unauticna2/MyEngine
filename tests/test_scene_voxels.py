"""Portable data tests: python -m unittest discover -s tests -v"""
import json
from pathlib import Path
import socket
import tempfile
import unittest
from engine_scene import SceneDocument
from engine_voxels import VoxelGrid
from engine_gl import inverse,multiply,model_matrix
from engine_editor_link import Channel

class DataTests(unittest.TestCase):
    def document(self):
        return SceneDocument({'model':['assets/Cube.obj'], 'positions':[{'x':1,'w':.3}],
            'colors':[{'r':1}], 'customColumn':[{'keep':True}], 'customSetting':{'important':123}})
    def test_roundtrip_unknown_data(self):
        d=self.document();d.add();d.duplicate(0);d.remove(1)
        self.assertEqual(d.data['customColumn'],[{'keep':True},{'keep':True}])
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'scene.json';d.save(p);self.assertEqual(SceneDocument.load(p).data,d.data)
        self.assertEqual(d.data['customSetting']['important'],123)
        self.assertEqual(d.data['positions'][0]['w'],.3)
    def test_undo_redo_and_invalid_name(self):
        d=self.document();before=json.dumps(d.data);d.add();d.undo();self.assertEqual(json.dumps(d.data),before)
        d.redo();self.assertEqual(len(d.data['model']),2)
        obj=d.object(1);obj['names']=d.data['names'][0]
        with self.assertRaises(ValueError):d.set_object(1,obj)
        self.assertNotEqual(d.data['names'][0],d.data['names'][1])
    def test_old_maps_load(self):
        root=Path(__file__).resolve().parent.parent
        for p in root.glob('map*.json'):
            d=SceneDocument.load(p);self.assertEqual(len(d.data['model']),len(d.data['voxels']))
    def test_grid_index_and_clone(self):
        g=VoxelGrid((3,4,5),.1);g.set(2,3,4,(1,2,3,255));self.assertEqual(g.pixels[-4:],bytes((1,2,3,255)))
        clone=g.clone();clone.set(2,3,4,(0,0,0,0));self.assertEqual(g.pixels[-1],255)
        for bad in ((0,2,2),(257,1,1),(2.5,2,2)):
            with self.assertRaises(ValueError):VoxelGrid(bad)
        with self.assertRaises(IndexError):g.set(3,0,0)
    def test_transform_inverse(self):
        m=model_matrix((5,2,-7),(15,23,-44),(2,.5,-3));identity=multiply(m,inverse(m))
        for i,v in enumerate(identity):self.assertAlmostEqual(v,1 if i%5==0 else 0,places=6)
    def test_grid_assets(self):
        root=Path(__file__).resolve().parent.parent
        for p in (root/'assets').glob('*.vxl.json'):
            g=VoxelGrid.load(p);self.assertGreater(sum(g.pixels[3::4]),0)
    def test_transport_order(self):
        a,b=socket.socketpair();left=Channel(a);right=Channel(b)
        try:
            for i in range(20):left.send({'op':'test','i':i,'unicode':'Сцена'})
            left.poll();messages=right.poll();self.assertEqual([m['i'] for m in messages],list(range(20)))
            self.assertEqual(messages[-1]['unicode'],'Сцена')
            left.close();right.poll();self.assertTrue(right.closed)
        finally:left.close();right.close()

if __name__=='__main__':unittest.main()
