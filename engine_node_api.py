"""Developer-defined Blueprint nodes. Plugins are Python and require project trust."""
from pathlib import Path
import types

DEFINITIONS={};LOADED=[];PLUGIN_ROOT=None

def definition(kind):
 value=DEFINITIONS.get(kind)
 if value is not None:
  from engine_trust import allowed
  if PLUGIN_ROOT is None or not allowed(PLUGIN_ROOT):raise PermissionError('Developer node scripts are blocked for this project')
 return value
class Context:
 def __init__(self,graph,node):self.graph=graph;self.node=node;self.params=graph.nodes[node]['params']
 def input(self,name):return self.graph.value(self.node,name)
 def literal(self,name):return repr(self.params[name])

class NodeAPI:
 def __init__(self):self.pending={}
 def define(self,kind,*,title=None,hint='',params=None,inputs=None,outputs=None,expression=None,action=None):
  from engine_blueprints import SPECS
  if not isinstance(kind,str) or not kind or kind in SPECS or kind in self.pending:raise ValueError('Node kind already exists or empty: '+str(kind))
  ins=dict(inputs or {});outs=dict(outputs or {});valid={'exec','number','bool'}
  if any(t not in valid for t in [*ins.values(),*outs.values()]):raise ValueError('Node ports support exec, number and bool')
  if (expression is None)==(action is None):raise ValueError('Specify exactly one expression or action generator')
  if expression and (len(outs)!=1 or 'exec' in ins.values() or 'exec' in outs.values()):raise ValueError('Expression nodes have one typed data output')
  if action and (ins.get('in')!='exec' or outs not in ({},{'next':'exec'})):raise ValueError('Action requires exec in and optional next')
  self.pending[kind]=((title or kind,hint,dict(params or {}),ins,outs),expression,action)

def load_plugins(root):
 global PLUGIN_ROOT
 from engine_trust import allowed
 from engine_blueprints import SPECS
 root=Path(root).resolve()
 if not allowed(root):raise PermissionError('Trust project scripts before loading developer node plugins')
 api=NodeAPI();old={k:SPECS.pop(k) for k in tuple(DEFINITIONS) if k in SPECS}
 try:
  paths=sorted((root/'plugins/nodes').glob('*.py'))
  for path in paths:
   path.resolve().relative_to(root)
   if path.stat().st_size>1024*1024:raise ValueError('Node plugin exceeds 1 MiB')
   module=types.ModuleType('developer_nodes');module.__file__=str(path)
   exec(compile(path.read_text(encoding='utf-8-sig'),str(path),'exec'),module.__dict__)
   module.register(api)
 except Exception:
  SPECS.update(old);raise
 DEFINITIONS.clear();LOADED[:]=[p.relative_to(root).as_posix() for p in paths]
 PLUGIN_ROOT=root
 for kind,(spec,expression,action) in api.pending.items():SPECS[kind]=spec;DEFINITIONS[kind]=(expression,action)
 return list(api.pending)
