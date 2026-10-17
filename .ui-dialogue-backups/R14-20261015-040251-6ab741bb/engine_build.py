"""Export a Windows player: one named EXE and one Data folder; no player-side Python install."""
import configparser
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import zipfile
from engine_projects import safe_name,inside,project_scenes
from engine_scene import atomic_json,SceneDocument

SKIP_DIRS={'build','builds','__pycache__','tests','legacy','node_modules','venv','.venv'}
SKIP_FILES={'python.ini','engine.log','build.json','project.myengine.json','README.txt','setup_python.py','launch_editor.py','MyEngine2Editor.py','MyEngineHub.py','build-options.json'}

def project_prefabs(root):
    root=Path(root)
    return [p.relative_to(root).as_posix() for p in root.rglob('*.prefab.json')
            if not p.is_symlink() and not any(part.startswith('.') or part.lower() in SKIP_DIRS for part in p.relative_to(root).parts)]

def fragment(root,name):
    if name.endswith('.prefab.json'):
        from engine_prefabs import load_prefab
        return load_prefab(root/name)
    return SceneDocument.load(root/name).data

def project_asset(root,path):
    # Match the case-insensitive asset loader, while retaining the root check.
    from engine_assets import asset_path
    inside(root,path)
    return inside(root,asset_path(root,path))

def is_x64_pe(path):
    try:
        with Path(path).open('rb') as f:
            head=f.read(64)
            if len(head)<64 or head[:2]!=b'MZ':return False
            offset=struct.unpack_from('<I',head,60)[0];f.seek(offset)
            return f.read(6)==b'PE\0\0d\x86'
    except OSError:return False

def validate_project(root,scene):
    root=Path(root).resolve();scene=inside(root,scene)
    if not scene.is_file():raise ValueError('Select an existing start scene.')
    SceneDocument.load(scene)
    for name in project_scenes(root)+project_prefabs(root):
        d=SceneDocument(build_scene(fragment(root,name)))
        for k in ('model','textures','scripts','voxels'):
            for value in d.data[k]:
                paths=value if isinstance(value,list) else [value]
                for p in paths:
                    if isinstance(p,dict):p=p.get('path')
                    if not p:continue
                    if Path(p).is_absolute() or ':' in p:raise ValueError(f'{name}: import this asset into the project and use a relative path: {p}')
                    try:project_asset(root,p)
                    except FileNotFoundError:raise FileNotFoundError(f'{name}: missing {p}') from None
        from engine_skybox import sky_paths
        for p in sky_paths(root,d.data.get('skybox')):
            if Path(p).is_absolute() or ':' in p:raise ValueError('Sky paths must be relative')
            project_asset(root,p)
        sun=d.data.get('sun')
        if sun:
            p=sun if isinstance(sun,str) else sun['texture']
            if Path(p).is_absolute() or ':' in p:raise ValueError('Sun paths must be project-relative')
            project_asset(root,p)
        if d.data.get('ui'):
            from engine_ui import load_document,image_paths
            from engine_ui_content import media_paths
            ui=project_asset(root,d.data['ui']);document=load_document(ui)
            for image in list(image_paths(document,include_background=bool(d.data.get('uiBackground',False))))+list(media_paths(document)):project_asset(root,(ui.parent/image).relative_to(root).as_posix())
        controller=d.data.get('camera',{}).get('controller',{})
        if controller.get('script'):
            p=controller['script']
            if Path(p).is_absolute() or ':' in p:raise ValueError('Character script must be project-relative')
            project_asset(root,p)
    return scene.relative_to(root).as_posix()

def build_scene(data):
    """Apply build flags without modifying the editable scene."""
    from copy import deepcopy
    d=SceneDocument(data);out=deepcopy(d.data);keep=[i for i in range(len(out['model'])) if not out['editorOnly'][i]]
    for key in d.columns():out[key]=[out[key][i] for i in keep]
    for i,omit in enumerate(out['omitModelInBuild']):
        if not omit:continue
        out['visible'][i]=False;out['textures'][i]=None
        collider=out['colliders'][i]
        if collider is None and out['rigidbodies'][i] is not None and out['rigidbodies'][i] is not False:
            collider={'type':'box'};out['colliders'][i]=collider
        collider=collider or {};kind=collider.get('type','box')
        if collider and out['model'][i] and out['model'][i].lower().endswith('.4d'):continue
        if collider and kind=='box' and not collider.get('size') and (out['model'][i] or out['voxels'][i]):
            # The export pass below bakes the original bounds before removing the render asset.
            continue
        if kind not in ('mesh','voxel'):out['model'][i]=None;out['voxels'][i]=None
    out.pop('editorOnly',None);out.pop('omitModelInBuild',None)
    return out

def prepare_build_scenes(root,data):
    from engine_skybox import sky_settings
    from engine_assets import load_layers
    from engine_voxels import VoxelGrid
    candidates=set();used=set()
    for name in project_scenes(root)+project_prefabs(root):
        if not (data/name).is_file():continue  # Respect explicit path exclusions.
        original=fragment(root,name);out=build_scene(original)
        for k in ('model','textures','voxels'):
            for p in original[k]:
                if isinstance(p,dict):p=p.get('path')
                if p:candidates.add(p)
        omitted=[original['omitModelInBuild'][i] for i in range(len(original['model'])) if not original['editorOnly'][i]]
        for i,model in enumerate(out['model']):
            # Model-only exclusions keep gameplay and an explicit collision volume.
            if omitted[i] and (model or out['voxels'][i]):
                col=out['colliders'][i]
                if col and model and model.lower().endswith('.4d'):continue
                if col and col.get('type','box')=='box' and not col.get('size'):
                    if out['voxels'][i] or model and model.lower().endswith('.vox'):
                        v=out['voxels'][i] or model;v={'path':v} if isinstance(v,str) else v
                        g=VoxelGrid.load(project_asset(root,v['path']),v.get('cellSize'),v.get('modelIndex'))
                        col['size']=[x*g.cell_size for x in g.size]
                        if col.get('center') is None:col['center']=[0,0,0]
                        if v.get('wSize') is not None and col.get('wSize') is None:col['wSize']=v['wSize']
                    else:
                        layers=load_layers(project_asset(root,model));lo=[min(l.minimum[k] for l in layers) for k in range(3)];hi=[max(l.maximum[k] for l in layers) for k in range(3)]
                        col['size']=[max(1e-5,b-a) for a,b in zip(lo,hi)]
                        if col.get('center') is None:col['center']=[(a+b)/2 for a,b in zip(lo,hi)]
                    out['model'][i]=None;out['voxels'][i]=None
        if out.get('skybox'):out['skybox']=sky_settings(root,out['skybox'])
        for k in ('model','textures','voxels'):
            for p in out[k]:
                if isinstance(p,dict):p=p.get('path')
                if p:used.add(p)
        if out.get('ui'):
            from engine_ui import load_document,image_paths
            from engine_ui_content import media_paths
            ui=project_asset(root,out['ui']);used.add(out['ui'])
            uidoc=load_document(ui)
            used.update((ui.parent/p).relative_to(root).as_posix() for p in list(image_paths(uidoc,include_background=bool(out.get('uiBackground',False))))+list(media_paths(uidoc)))
        from engine_skybox import sky_paths
        used.update(sky_paths(root,out.get('skybox')))
        if out.get('sun'):used.add(out['sun'] if isinstance(out['sun'],str) else out['sun']['texture'])
        atomic_json(data/name,{'format':1,'kind':'prefab','scene':out} if name.endswith('.prefab.json') else out)
    # Explicit flags allow stripping these assets only when no other built scene references them.
    # Retain any path mentioned literally in a Python script and explicit buildKeepAssets entries.
    scripts='\n'.join(p.read_text(encoding='utf-8-sig',errors='replace') for p in root.rglob('*.py') if 'Builds' not in p.parts and '.git' not in p.parts)
    for name in project_scenes(root):used.update(SceneDocument.load(root/name).data.get('buildKeepAssets',[]))
    used_folded={p.casefold() for p in used};scripts=scripts.casefold()
    for p in candidates:
        if p.casefold() in used_folded or p.casefold() in scripts:continue
        try:target=project_asset(data,p)
        except FileNotFoundError:continue
        if target.is_file():target.unlink()


def copy_project(root,data,progress,options=None):
    from engine_build_options import load,excluded
    options=options or load(root)
    for base,dirs,files in os.walk(root):
        dirs[:]=[d for d in dirs if not d.startswith('.') and d.lower() not in SKIP_DIRS and not (Path(base)/d).is_symlink()]
        for name in files:
            p=Path(base)/name
            if name.startswith('.') or name in SKIP_FILES or p.is_symlink() or p.suffix.lower() in ('.exe','.exp','.pdb','.rc','.cmd','.pyc') or excluded(p.relative_to(root),options):continue
            if p.parent==root and (name.startswith('engine_') or name.startswith('MyEngine')):continue
            dest=data/p.relative_to(root);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
    progress('Project assets and scripts copied.')

def bundle_python(home,target,include_packages=False,progress=lambda x:None):
    home=Path(home).resolve();target=Path(target)
    dlls=[p for p in home.glob('python3*.dll') if p.stem[6:].isdigit() and p.stem!='python3' and not p.stem.endswith('_d')]
    if len(dlls)!=1 or not is_x64_pe(dlls[0]):raise ValueError('Choose a normal CPython 3.11–3.13 x64 installation (not a virtualenv or ARM build).')
    dll=dlls[0];tag=dll.stem
    if tag not in ('python311','python312','python313'):raise ValueError('This engine supports regular CPython 3.11–3.13 x64.')
    if not (home/'Lib/encodings/__init__.py').is_file():raise ValueError('The Python standard library is missing in this installation.')
    target.mkdir(parents=True)
    # Includes CPython and its app-local VC runtime, without copying python.exe.
    for p in home.glob('*.dll'):shutil.copy2(p,target/p.name)
    if not (target/'vcruntime140.dll').is_file():raise ValueError('vcruntime140.dll is missing from the Python installation; repair Python first.')
    if (home/'DLLs').is_dir():
        shutil.copytree(home/'DLLs',target/'DLLs',ignore=shutil.ignore_patterns('*.pdb','*.exe','__pycache__'))
    excluded={'site-packages','__pycache__','test','tests','idlelib','tkinter','turtledemo','ensurepip'}
    with zipfile.ZipFile(target/(tag+'.zip'),'w',zipfile.ZIP_DEFLATED) as z:
        for base,dirs,files in os.walk(home/'Lib'):
            dirs[:]=[d for d in dirs if d not in excluded]
            for name in files:
                p=Path(base)/name
                if p.suffix in ('.py','.txt','.json','.pem') and not p.is_symlink():z.write(p,p.relative_to(home/'Lib').as_posix())
    if include_packages and (home/'Lib/site-packages').is_dir():
        progress('Copying site-packages (this can take time)…')
        shutil.copytree(home/'Lib/site-packages',target/'site-packages',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    (target/(tag+'._pth')).write_text(f'{tag}.zip\n.\nDLLs\nsite-packages\n..\nimport site\n',encoding='utf-8')
    if (home/'LICENSE.txt').is_file():shutil.copy2(home/'LICENSE.txt',target/'LICENSE.txt')
    progress('Private Python runtime copied.')
    return dll.name

def export_game(engine_root,project_root,output_parent,name,scene,python_home=None,include_packages=False,progress=lambda x:None,exclude_extensions=None,exclude_files=None):
    engine_root=Path(engine_root).resolve();root=Path(project_root).resolve();parent=Path(output_parent).resolve();name=safe_name(name)
    destination=parent/name
    if destination.exists():raise FileExistsError('This build folder already exists. Choose a new name or output folder.')
    if root.is_relative_to(destination):raise ValueError('Build folder cannot contain the project.')
    if destination.is_relative_to(root) and destination.relative_to(root).parts[0].lower()!='builds':
        raise ValueError('Inside the project, export only under Builds. You can also choose a folder outside the project.')
    from engine_build_options import load,normalized,excluded
    options=load(root) if exclude_extensions is None and exclude_files is None else normalized(exclude_extensions,exclude_files)
    scene=validate_project(root,scene);exe=engine_root/'MyEngine2.exe'
    if not is_x64_pe(exe):raise ValueError('Run build.cmd first: MyEngine2.exe x64 is missing.')
    if b'EngineGetRuntimeFlags\0' not in exe.read_bytes():raise ValueError('Rebuild MyEngine2.exe with the 2.5 build.cmd before exporting.')
    home=Path(python_home or sys.base_prefix).resolve()
    if sys.platform!='win32' and python_home is None:raise RuntimeError('Player builds require a Windows x64 Python installation.')
    parent.mkdir(parents=True,exist_ok=True);stage=Path(tempfile.mkdtemp(prefix='.myengine-build-',dir=parent))
    try:
        data=stage/'Data';data.mkdir();progress('Copying project…');copy_project(root,data,progress,options)
        prepare_build_scenes(root,data)
        validate_project(data,scene)
        from engine_trust import allowed,set_allowed
        set_allowed(data,allowed(root))
        for p in engine_root.glob('engine_*.py'):
            if p.name not in ('engine_build.py','engine_build_ui.py','engine_projects.py'):shutil.copy2(p,data/p.name)
        shutil.copy2(engine_root/'PNGJSONUnitylity.py',data/'PNGJSONUnitylity.py')
        video_dll=engine_root/'MyEngineVideo.dll'
        if video_dll.is_file() and not excluded(video_dll.name,options):shutil.copy2(video_dll,data/video_dll.name)
        for helper in ('video_host.ps1',):
            origin=engine_root/'tools'/helper
            if origin.is_file() and not excluded('tools/'+helper,options):
                (data/'tools').mkdir(exist_ok=True);shutil.copy2(origin,data/'tools'/helper)
        shutil.copytree(engine_root/'shaders',data/'shaders',dirs_exist_ok=True)
        for filename in ('Slice4D.dll','MyEngineUI.dll'):
            native=engine_root/filename
            if native.exists() and not excluded(filename,options):shutil.copy2(native,data/filename)
        from engine_ui_content import media_paths
        from engine_ui import load_document
        for ui_asset in data.rglob('*.ui.json'):
            if any(media_paths(load_document(ui_asset))):
                for required in ('MyEngineVideo.dll','tools/video_host.ps1'):
                    if not (data/required).is_file():raise ValueError('Local UI videos require '+required+'. Remove its build exclusion or install R12 fully.')
        dll=bundle_python(home,data/'Python',include_packages,progress)
        (data/'python.ini').write_text(f'[Python]\nHome=.\\Python\nDLL=.\\Python\\{dll}\n',encoding='utf-16')
        atomic_json(data/'build.json',{'engineVersion':'2.5','name':name,'mainScene':scene})
        shutil.copy2(exe,stage/(name+'.exe'))
        if sorted(p.name for p in stage.iterdir())!=sorted(['Data',name+'.exe']):raise RuntimeError('Invalid player layout')
        stage.rename(destination);progress('Build complete: '+str(destination));return destination
    except BaseException:
        shutil.rmtree(stage,ignore_errors=True);raise

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--project',required=True);p.add_argument('--output',required=True);p.add_argument('--name',required=True);p.add_argument('--scene',required=True);p.add_argument('--include-packages',action='store_true')
    a=p.parse_args();export_game(Path(__file__).parent,a.project,a.output,a.name,a.scene,include_packages=a.include_packages,progress=print)
