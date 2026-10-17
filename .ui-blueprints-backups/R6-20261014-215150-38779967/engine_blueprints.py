"""Typed Blueprint graph -> plain Python inside a delimited generated region."""
from pathlib import Path
import ast
import json
import math
import os
import tempfile
from engine_scene import atomic_json

# title, hint, parameter defaults, typed inputs, typed outputs. exec ports are white.
SPECS={
 'Start':('Start','Runs once when Play starts.',{}, {}, {'next':'exec'}),
 'Update':('Update','Runs each frame; use dt for speed per second.',{}, {}, {'next':'exec'}),
 'FixedUpdate':('Fixed Update','Runs before each physics step.',{}, {}, {'next':'exec'}),
 'Number':('Number','A finite numeric constant.',{'value':1},{},{'value':'number'}),
 'DeltaTime':('Delta time','Seconds of the current update.',{}, {}, {'value':'number'}),
 'Add':('Add','Adds two numbers.',{'a':0,'b':0},{'a':'number','b':'number'},{'value':'number'}),
 'Multiply':('Multiply','Multiplies two numbers.',{'a':1,'b':1},{'a':'number','b':'number'},{'value':'number'}),
 'KeyDown':('Key held','True while a key is held: W, A, SPACE, F1…',{'key':'W'}, {}, {'value':'bool'}),
 'KeyPressed':('Key pressed','True only on the frame a key becomes pressed.',{'key':'SPACE'}, {}, {'value':'bool'}),
 'Compare':('Greater than','True when a > b.',{'a':0,'b':0},{'a':'number','b':'number'},{'value':'bool'}),
 'Branch':('Branch','Executes only the True or False chain.',{'condition':True},{'in':'exec','condition':'bool'},{'true':'exec','false':'exec'}),
 'Move':('Move','Moves this object. Connect speed*dt to an axis.',{'x':0,'y':0,'z':0,'w':0},{'in':'exec','x':'number','y':'number','z':'number','w':'number'},{'next':'exec'}),
 'Rotate':('Rotate','Adds XYZ rotation in degrees.',{'x':0,'y':30,'z':0},{'in':'exec','x':'number','y':'number','z':'number'},{'next':'exec'}),
 'Rotate4D':('Rotate 4D','Adds XW/YW/ZW rotation in degrees.',{'xw':0,'yw':0,'zw':0},{'in':'exec','xw':'number','yw':'number','zw':'number'},{'next':'exec'}),
 'Velocity':('Set velocity','Sets Rigidbody velocity in metres/sec; use Fixed Update.',{'x':0,'y':0,'z':0},{'in':'exec','x':'number','y':'number','z':'number'},{'next':'exec'}),
 'Impulse':('Impulse','Adds an impulse to this object Rigidbody.',{'x':0,'y':5,'z':0},{'in':'exec','x':'number','y':'number','z':'number'},{'next':'exec'}),
 'Spawn':('Spawn','Creates an object; model and script are relative project paths.',{'model':'assets/Cube.obj','script':'','x':0,'y':2,'z':0},{'in':'exec','x':'number','y':'number','z':'number'},{'next':'exec'}),
 'LoadScene':('Load scene','Requests a scene switch at the frame boundary.',{'path':'scenes/main.json'},{'in':'exec'},{'next':'exec'}),
 'Print':('Log','Writes text to the Console.',{'text':'Hello from Blueprint'},{'in':'exec'},{'next':'exec'}),
 'Destroy':('Destroy self','Destroys this object after the update.',{},{'in':'exec'},{}),
 'Character':('Player physics','Switch player to fly or walk. Customize more in Python.',{'mode':'walk'},{'in':'exec'},{'next':'exec'}),
}
SPECS['Prefab']=('Spawn prefab','Creates the objects in a prefab without changing the scene.',{'path':'assets/prefabs/Example.prefab.json','x':0,'y':0,'z':0},{'in':'exec','x':'number','y':'number','z':'number'},{'next':'exec'})
BEGIN='# region MYENGINE_BLUEPRINT'
END='# endregion MYENGINE_BLUEPRINT'

def example():
    return {'format':1,'nodes':[
        {'id':'1','type':'Update','x':40,'y':50,'params':{}},
        {'id':'2','type':'DeltaTime','x':40,'y':250,'params':{}},
        {'id':'3','type':'Multiply','x':300,'y':240,'params':{'a':30,'b':1}},
        {'id':'4','type':'Rotate','x':590,'y':60,'params':{'x':0,'y':0,'z':0}}],
        'links':[['1','next','4','in'],['2','value','3','b'],['3','value','4','y']]}

class Graph:
    def __init__(self,data):
        if data.get('format')!=1:raise ValueError('Unsupported Blueprint format')
        ns=data.get('nodes',[]);ls=data.get('links',[])
        if len(ns)>256 or len(ls)>1024:raise ValueError('Limit: 256 nodes / 1024 links')
        self.nodes={};self.inputs={};self.flows={};self.events={};self.used=set()
        for n in ns:
            nid=n.get('id');kind=n.get('type')
            if not isinstance(nid,str) or not nid or nid in self.nodes:raise ValueError('Node IDs must be unique nonempty strings')
            if kind not in SPECS:raise ValueError('Unknown node '+str(kind))
            node=dict(n);node['params']=dict(SPECS[kind][2]);node['params'].update(n.get('params',{}));self.nodes[nid]=node
            if kind in ('Start','Update','FixedUpdate'):
                if kind in self.events:raise ValueError('Use one '+kind+' node per graph')
                self.events[kind]=nid
        for link in ls:
            if len(link)!=4:raise ValueError('Link must be [source,port,target,port]')
            a,ap,b,bp=link
            if a not in self.nodes or b not in self.nodes:raise ValueError('Link refers to missing node')
            at=SPECS[self.nodes[a]['type']][4].get(ap);bt=SPECS[self.nodes[b]['type']][3].get(bp)
            if at is None or bt is None or at!=bt:raise ValueError('Incompatible ports: '+str(link))
            if at=='exec':
                if (a,ap) in self.flows:raise ValueError('An execution output has only one connection')
                self.flows[a,ap]=b
            else:
                if (b,bp) in self.inputs:raise ValueError('An input has only one connection')
                self.inputs[b,bp]=(a,ap)
        # Reject disconnected cycles too, rather than allowing latent infinite generation.
        adjacency={i:[] for i in self.nodes}
        for a,ap,b,bp in ls:adjacency[a].append(b)
        done=set();visiting=set()
        def visit(i):
            if i in visiting:raise ValueError('Cycles are not supported; use Update / Fixed Update to repeat')
            if i in done:return
            visiting.add(i)
            for j in adjacency[i]:visit(j)
            visiting.remove(i);done.add(i)
        for i in self.nodes:visit(i)
        self.lines=[]
    def value(self,nid,port):
        if (nid,port) in self.inputs:return self.expression(self.inputs[nid,port][0])
        value=self.nodes[nid]['params'][port];kind=SPECS[self.nodes[nid]['type']][3][port]
        if kind=='bool':
            if not isinstance(value,bool):raise ValueError('Boolean parameter required')
        elif isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value):raise ValueError('Finite number required: '+port)
        return repr(value)
    def expression(self,nid):
        self.used.add(nid);n=self.nodes[nid];kind=n['type'];p=n['params']
        if kind=='Number':
            value=p['value']
            if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value):raise ValueError('Number must be finite')
            return repr(value)
        if kind=='DeltaTime':return 'dt'
        if kind in ('KeyDown','KeyPressed'):return 'self.world.input.'+('down' if kind=='KeyDown' else 'pressed')+'('+repr(str(p['key']))+')'
        if kind in ('Add','Multiply','Compare'):return '('+self.value(nid,'a')+{'Add':' + ','Multiply':' * ','Compare':' > '}[kind]+self.value(nid,'b')+')'
        from engine_node_api import definition,Context
        custom=definition(kind)
        if custom and custom[0]:
            expression=custom[0](Context(self,nid))
            ast.parse(expression,mode='eval');return '('+expression+')'
        raise ValueError('Not a data node: '+kind)
    def emit(self,indent,line):
        if len(self.lines)>20000:raise ValueError('Graph expands to too much Python; simplify branches')
        self.lines.append('    '*indent+line)
    def chain(self,nid,indent):
        if nid is None:self.emit(indent,'pass');return
        self.used.add(nid);n=self.nodes[nid];kind=n['type'];p=n['params']
        self.emit(indent,'# '+kind+' node '+repr(nid))
        if kind=='Branch':
            self.emit(indent,'if '+self.value(nid,'condition')+':');self.chain(self.flows.get((nid,'true')),indent+1)
            self.emit(indent,'else:');self.chain(self.flows.get((nid,'false')),indent+1);return
        def args(ports):return ', '.join(self.value(nid,k) for k in ports)
        if kind=='Move':line='self.entity.move('+args(('x','y','z','w'))+')'
        elif kind=='Rotate':line='self.entity.rotate('+args(('x','y','z'))+')'
        elif kind=='Rotate4D':line='self.entity.rotation4.set(*[a+b for a,b in zip(self.entity.rotation4, ('+args(('xw','yw','zw'))+'))])'
        elif kind=='Velocity':line='self.entity.rigidbody.velocity = ('+args(('x','y','z'))+')'
        elif kind=='Impulse':line='self.entity.rigidbody.add_force(('+args(('x','y','z'))+'), mode="impulse")'
        elif kind=='Spawn':line='self.world.instantiate('+repr(str(p['model']) or None)+', position=('+args(('x','y','z'))+'), scripts='+repr([str(p['script'])] if p['script'] else [])+')'
        elif kind=='Prefab':line='self.world.instantiate_prefab('+repr(str(p['path']))+', position=('+args(('x','y','z'))+'))'
        elif kind=='LoadScene':line='self.world.load_scene('+repr(str(p['path']))+')'
        elif kind=='Print':line='self.world.log('+repr(str(p['text']))+')'
        elif kind=='Destroy':line='self.entity.destroy()'
        elif kind=='Character':
            if p['mode'] not in ('walk','fly'):raise ValueError('Character mode must be walk or fly')
            line='self.world.camera.configure_physics('+repr(p['mode'])+')'
        else:
            from engine_node_api import definition,Context
            custom=definition(kind)
            if not custom or not custom[1]:raise ValueError('Not an action: '+kind)
            line=custom[1](Context(self,nid))
            if isinstance(line,list):line='\n'.join(line)
            if not isinstance(line,str):raise ValueError('Action generator must return Python text')
            ast.parse(line)
            for source_line in line.splitlines():self.emit(indent,source_line)
            target=self.flows.get((nid,'next'))
            if target:self.chain(target,indent)
            return
        if kind in ('Velocity','Impulse'):
            self.emit(indent,'if self.entity.rigidbody is not None:');self.emit(indent+1,line)
        else:self.emit(indent,line)
        target=self.flows.get((nid,'next'))
        if target:self.chain(target,indent)
    def compile(self):
        self.lines=[BEGIN]
        for kind,name in [('Start','start'),('Update','update'),('FixedUpdate','fixed_update')]:
            self.emit(0,'def _bp_'+name+'(self, dt=0.0):')
            event=self.events.get(kind)
            if event:self.used.add(event)
            self.chain(self.flows.get((event,'next')),1);self.lines.append('')
        self.lines.append(END);text='\n'.join(self.lines)
        ast.parse(text);return text

def generated_source(data,existing=None):
    graph=Graph(data);region=graph.compile()
    if existing is None:
        text='from engine_runtime import Behaviour\n\n'+region+'''\n\nclass Script(Behaviour):
    def start(self):
        _bp_start(self)

    def update(self, dt):
        _bp_update(self, dt)

    def fixed_update(self, dt):
        _bp_fixed_update(self, dt)

# Write your extra Python outside the generated region.
'''
    else:
        lines=existing.splitlines(keepends=True)
        starts=[i for i,l in enumerate(lines) if l.rstrip('\r\n')==BEGIN];ends=[i for i,l in enumerate(lines) if l.rstrip('\r\n')==END]
        if len(starts)!=1 or len(ends)!=1 or starts[0]>=ends[0]:raise ValueError('Choose a new Python file, or use a file already generated by Blueprints. No matching region found.')
        text=''.join(lines[:starts[0]])+region+'\n'+''.join(lines[ends[0]+1:])
    ast.parse(text)
    return text,sorted(set(graph.nodes)-graph.used)

def save_python(path,data):
    path=Path(path);text,unused=generated_source(data,path.read_text(encoding='utf-8-sig') if path.exists() else None)
    path.parent.mkdir(parents=True,exist_ok=True);fd,tmp=tempfile.mkstemp(dir=path.parent,suffix='.tmp')
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:f.write(text)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    return unused
