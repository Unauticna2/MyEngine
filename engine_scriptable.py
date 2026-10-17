"""JSON Scriptable Objects: shared data assets, independent runtime clones, typed fields."""
from copy import deepcopy
from pathlib import Path
from engine_scene import atomic_json
import json,math

def validate(data,schema):
 if not isinstance(data,dict) or not isinstance(schema,dict):raise ValueError('data and schema must be objects')
 for name,spec in schema.items():
  if name not in data:
   if 'default' in spec:data[name]=deepcopy(spec['default'])
   elif spec.get('required',False):raise ValueError('Missing field: '+name)
   else:continue
  value=data[name];kind=spec.get('type','any')
  valid={'any':True,'float':isinstance(value,(int,float)) and not isinstance(value,bool),'int':type(value) is int,'bool':type(value) is bool,'string':isinstance(value,str),'list':isinstance(value,list),'object':isinstance(value,dict),'vec3':isinstance(value,list) and len(value)==3 and all(type(x) in (int,float) and math.isfinite(x) for x in value)}
  if kind not in valid or not valid[kind]:raise ValueError(name+': expected '+kind)
  if type(value) in (int,float):
   if not math.isfinite(value):raise ValueError(name+': finite number required')
   if 'min' in spec and value<spec['min'] or 'max' in spec and value>spec['max']:raise ValueError(name+': outside allowed range')
  if 'choices' in spec and value not in spec['choices']:raise ValueError(name+': not in choices')
 json.dumps(data,allow_nan=False);return data

class ScriptableObject:
 def __init__(self,data=None,*,type_name='Data',schema=None,path=None):
  self.type_name=str(type_name);self.schema=deepcopy(schema or {});self._data=validate(deepcopy(data or {}),self.schema);self.path=Path(path) if path else None
 def __getitem__(self,key):return deepcopy(self._data[key])
 def __setitem__(self,key,value):
  candidate=deepcopy(self._data);candidate[key]=deepcopy(value);validate(candidate,self.schema);self._data=candidate
 def get(self,key,default=None):return deepcopy(self._data.get(key,default))
 def to_dict(self):return deepcopy(self._data)
 def clone(self):return ScriptableObject(self._data,type_name=self.type_name,schema=self.schema)
 @classmethod
 def load(cls,path):
  p=Path(path)
  if p.stat().st_size>8*1024*1024:raise ValueError('Scriptable Object exceeds 8 MiB')
  d=json.loads(p.read_text(encoding='utf-8-sig'))
  if d.get('format')!=1 or d.get('kind')!='scriptable':raise ValueError('Not a Scriptable Object')
  return cls(d.get('data',{}),type_name=d.get('type','Data'),schema=d.get('schema',{}),path=p)
 def save(self,path=None):
  target=Path(path) if path else self.path
  if target is None:raise ValueError('Specify the asset path')
  atomic_json(target,{'format':1,'kind':'scriptable','type':self.type_name,'schema':self.schema,'data':self._data});self.path=target
