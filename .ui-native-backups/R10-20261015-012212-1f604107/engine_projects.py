"""Project documents and recent-project registry, independent of Tk."""
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from datetime import datetime,timezone
from engine_scene import atomic_json,SceneDocument

VERSION='2.5'
PROJECT_FILE='project.myengine.json'

def safe_name(value):
    name=str(value).strip()
    if not name or len(name)>80 or re.search(r'[<>:"/\\|?*\x00-\x1f]',name) or name.endswith('.'):
        raise ValueError('Use a name of 1–80 characters without Windows filename symbols.')
    if name.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:
        raise ValueError('This filename is reserved by Windows.')
    return name

def inside(root,path):
    root=Path(root).resolve();p=(root/Path(path)).resolve()
    if not p.is_relative_to(root):raise ValueError(f'File must be inside the project: {path}')
    return p

def read_project(root):
    root=Path(root).resolve()
    data=json.loads((root/PROJECT_FILE).read_text(encoding='utf-8-sig'))
    if data.get('format')!=1:raise ValueError('Unsupported MyEngine project format')
    if not inside(root,data['mainScene']).is_file():raise ValueError('Project start scene is missing')
    return data

def create_scene(root, path):
    """Create a named empty scene inside an existing project."""
    target=inside(root,path)
    if target.suffix.lower()!='.json':raise ValueError('Use a .json filename for the scene.')
    target=target.with_suffix('.json')
    if target.name.lower()==PROJECT_FILE or target.name.lower().endswith(('.prefab.json','.vxl.json','.ui.json','.scriptable.json','.blueprint.json','.sky.json')):
        raise ValueError('Choose a scene filename, for example scenes/Level2.json.')
    title=safe_name(target.stem)
    if target.exists():raise FileExistsError('A file with this name already exists. Choose a new scene name.')
    document=SceneDocument.empty(title)
    document.save_new(target)
    return target,document

def create_project(engine_root,parent,name,template='Basic 3D'):
    engine_root=Path(engine_root).resolve();parent=Path(parent).resolve();name=safe_name(name)
    parent.mkdir(parents=True,exist_ok=True);target=parent/name
    if target.exists():raise FileExistsError('Choose a new project folder; this one already exists.')
    if template not in ('Basic 3D','VOX + 4D demo','Empty'):raise ValueError('Unknown template')
    temporary=Path(tempfile.mkdtemp(prefix='.myengine-new-',dir=parent))
    try:
        for sub in ('assets','scripts','textures','scenes','plugins/nodes'):(temporary/sub).mkdir(parents=True)
        if template=='VOX + 4D demo':
            data=json.loads((engine_root/'map-vox.json').read_text(encoding='utf-8'))
            for file in ('Cube.obj','vox.vox','spherecube.4d'):shutil.copy2(engine_root/'assets'/file,temporary/'assets'/file)
        elif template=='Basic 3D':
            shutil.copy2(engine_root/'assets/Cube.obj',temporary/'assets/Cube.obj')
            data={'model':['assets/Cube.obj','assets/Cube.obj'],'names':['Floor','Cube'],
                  'positions':[{'y':-.25},{'y':2}], 'scales':[{'x':8,'y':.25,'z':8},{'x':.5,'y':.5,'z':.5}],
                  'colors':[{'r':.35,'g':.4,'b':.5},{'r':.3,'g':.7,'b':1}],
                  'colliders':[{'type':'box'},{'type':'box'}], 'rigidbodies':[None,{'mass':1,'freezeRotation':True}]}
        else:data={'model':[]}
        data['title']=name
        data.setdefault('camera',{'position':{'x':0,'y':3,'z':10},'pitch':12,'yaw':0,'freeFly':True})
        SceneDocument(data).save(temporary/'scenes/main.json')
        atomic_json(temporary/PROJECT_FILE,{'format':1,'name':name,'engineVersion':VERSION,'mainScene':'scenes/main.json'})
        temporary.rename(target)
    except BaseException:
        shutil.rmtree(temporary,ignore_errors=True);raise
    return target

def project_scenes(root):
    result=[];root=Path(root).resolve()
    for base,dirs,files in os.walk(root):
        dirs[:]=[d for d in dirs if not d.startswith('.') and d.lower() not in ('builds','build','__pycache__')]
        for name in sorted(files):
            if not name.endswith('.json') or name.endswith('.vxl.json') or name==PROJECT_FILE:continue
            p=Path(base)/name
            try:
                d=json.loads(p.read_text(encoding='utf-8-sig'))
                if isinstance(d,dict) and isinstance(d.get('model'),list):result.append(p.relative_to(root).as_posix())
            except (ValueError,OSError):pass
    return sorted(result)

def adopt_project(root,name,scene):
    root=Path(root).resolve()
    if (root/PROJECT_FILE).exists():raise FileExistsError('This folder already has project settings.')
    scene=inside(root,scene);SceneDocument.load(scene)
    atomic_json(root/PROJECT_FILE,{'format':1,'name':safe_name(name),'engineVersion':VERSION,'mainScene':scene.relative_to(root).as_posix()})
    return root

class Registry:
    def __init__(self,path=None):
        self.path=Path(path) if path else Path(os.environ.get('LOCALAPPDATA',Path.home()/'.local/share'))/'MyEngine2Hub/projects.json'
        try:self.entries=json.loads(self.path.read_text(encoding='utf-8'))['projects']
        except (OSError,ValueError,KeyError):self.entries=[]
    def remember(self,root):
        root=Path(root).resolve();data=read_project(root)
        self.entries=[x for x in self.entries if Path(x['path']).resolve()!=root]
        self.entries.insert(0,{'name':data['name'],'path':str(root),'opened':datetime.now(timezone.utc).isoformat(timespec='seconds')})
        self.save()
    def forget(self,root):
        root=Path(root).resolve();self.entries=[x for x in self.entries if Path(x['path']).resolve()!=root];self.save()
    def save(self):atomic_json(self.path,{'projects':self.entries[:100]})
