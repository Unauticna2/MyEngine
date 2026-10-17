"""Editor scene document. Preserves unknown scene keys and per-object columns."""
from copy import deepcopy
import json
import math
from pathlib import Path
import os
import tempfile

DEFAULTS = {'model': None, 'positions': {'x': 0, 'y': 0, 'z': 0},
            'rotations': {'x': 0, 'y': 0, 'z': 0}, 'scales': {'x': 1, 'y': 1, 'z': 1},
            'colors': {'r': 1, 'g': 1, 'b': 1}, 'names': None, 'textures': None,
            'scripts': [], 'colliders': None, 'rigidbodies': None,
            'rotations4D': {'xw':0,'yw':0,'zw':0}, 'layerSpacings': .1, 'voxels': None, 'active': True, 'visible': True, 'omitModelInBuild': False, 'editorOnly': False, 'scriptTrusted': True, 'castShadows': True, 'receiveShadows': True}


def atomic_json(path, data):
    path = Path(path)
    text = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name+'.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(text); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


class SceneDocument:
    def __init__(self, data):
        self.data = deepcopy(data)
        self.undo_stack = []; self.redo_stack = []
        self.validate()
        n = len(self.data['model'])
        for key, default in DEFAULTS.items():
            if key not in self.data: self.data[key] = [deepcopy(default) for _ in range(n)]
        for i, name in enumerate(self.data['names']):
            if not name: self.data['names'][i] = self.unique_name('Object')
        if len(set(self.data['names'])) != n: raise ValueError('Duplicate object names')

    @classmethod
    def empty(cls, title='NewScene'):
        """A standalone scene, with no assets or settings inherited from another."""
        return cls({'title': title, 'model': [],
                    'camera': {'position': {'x': 0, 'y': 3, 'z': 10},
                               'pitch': 12, 'yaw': 0, 'w': 0, 'freeFly': True}})

    @classmethod
    def load(cls, path):
        def unique(pairs):
            d = {}
            for k,v in pairs:
                if k in d: raise ValueError('Duplicate scene key: '+k)
                d[k] = v
            return d
        return cls(json.loads(Path(path).read_text(encoding='utf-8-sig'), object_pairs_hook=unique))

    def validate(self):
        d = self.data
        json.dumps(d, allow_nan=False)
        if not isinstance(d.get('model'), list) or len(d['model']) > 4096:
            raise ValueError('model must contain at most 4096 entries')
        n = len(d['model'])
        for k in DEFAULTS:
            if k in d and (not isinstance(d[k], list) or len(d[k]) != n):
                raise ValueError(f'{k}: expected {n} entries')
        names = d.get('names', [])
        actual = [x for x in names if x]
        if 'player' in actual or len(set(actual)) != len(actual):
            raise ValueError('Names must be unique; player is reserved')

    def columns(self):
        n = len(self.data['model'])
        # Unknown same-length arrays are object columns, preserved on add/delete.
        return [k for k,v in self.data.items() if isinstance(v,list) and len(v)==n and k not in ('buildKeepAssets',)]

    def checkpoint(self):
        self.undo_stack.append(deepcopy(self.data)); self.undo_stack = self.undo_stack[-64:]
        self.redo_stack.clear()

    def undo(self):
        if not self.undo_stack: return False
        self.redo_stack.append(self.data); self.data=self.undo_stack.pop(); return True

    def redo(self):
        if not self.redo_stack: return False
        self.undo_stack.append(self.data); self.data=self.redo_stack.pop(); return True

    def unique_name(self, base):
        name=base; i=1; names=self.data.get('names', [])
        while name in names or name=='player': name=f'{base} {i}'; i+=1
        return name

    def object(self, i): return {k:deepcopy(self.data[k][i]) for k in DEFAULTS}

    def set_object(self, i, obj):
        before = deepcopy(self.data)
        for k in DEFAULTS:
            if k in obj: self.data[k][i]=deepcopy(obj[k])
        try: self.validate()
        except Exception: self.data=before; raise
        self.undo_stack.append(before); self.undo_stack=self.undo_stack[-64:]; self.redo_stack.clear()

    def add(self, model=None, voxel=None):
        if len(self.data['model'])>=4096: raise ValueError('4096 object limit')
        self.checkpoint()
        name=self.unique_name('Voxel' if voxel else 'Cube' if model else 'Object')
        for k in self.columns(): self.data[k].append(deepcopy(DEFAULTS.get(k)))
        i=len(self.data['model'])-1
        self.data['model'][i]=model; self.data['names'][i]=name; self.data['voxels'][i]=voxel
        return i

    def duplicate(self, i):
        if len(self.data['model'])>=4096: raise ValueError('4096 object limit')
        self.checkpoint(); name=self.unique_name(self.data['names'][i])
        for k in self.columns(): self.data[k].append(deepcopy(self.data[k][i]))
        self.data['names'][-1]=name
        return len(self.data['model'])-1

    def remove(self, i):
        self.checkpoint()
        for k in self.columns(): del self.data[k][i]

    def save(self, path): self.validate(); atomic_json(path,self.data)

    def save_new(self, path):
        """Create only: never overwrite another scene, even after a name race."""
        self.validate()
        text = json.dumps(self.data, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        created = False
        try:
            with path.open('x', encoding='utf-8') as stream:
                created = True
                stream.write(text); stream.flush(); os.fsync(stream.fileno())
        except BaseException:
            if created: path.unlink(missing_ok=True)
            raise
