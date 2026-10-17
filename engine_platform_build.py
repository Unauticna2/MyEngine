"""Explicit target capabilities. Never label a stripped project a successful port."""
from pathlib import Path
import json,shutil,tempfile
from engine_projects import safe_name
from engine_build import validate_project,copy_project,prepare_build_scenes,export_game

TARGETS=('Windows x64','Linux x64 (experimental)','WebGL — port required','Android — port required')
PORT_LIMITATIONS={
 'WebGL':'WebGL needs an ES/WebGL renderer, a WebAssembly physics backend and a browser Python host. The Windows MASM executable, ctypes native libraries and desktop OpenGL 2.1 cannot run in a browser. No game files were discarded or exported.',
 'Android':'Android needs an ARM64 or WebAssembly physics backend, an OpenGL ES renderer and an Android Python host / input layer. Renaming the Windows executable or wrapping it in an APK cannot provide that. No game files were discarded or exported.'}

def export_linux(engine_root,project_root,output_parent,name,scene,progress=lambda x:None,exclude_extensions=None,exclude_files=None,release_options=None,**unused):
    from engine_build_options import load,normalized
    from engine_trust import allowed,set_allowed
    engine=Path(engine_root).resolve();root=Path(project_root).resolve();parent=Path(output_parent).resolve();name=safe_name(name);destination=parent/name
    if destination.exists():raise FileExistsError('Build folder already exists')
    if root.is_relative_to(destination) or destination.is_relative_to(root) and destination.relative_to(root).parts[0].lower()!='builds':raise ValueError('Export outside the project or into its Builds folder')
    native=engine/'platforms/linux'
    for filename in ('libMyEnginePhysics.so','libSlice4D.so'):
        p=native/filename
        if not p.is_file() or p.read_bytes()[:5]!=b'\x7fELF\x02':raise RuntimeError('Build the Linux x86_64 native kernels with tools/build_linux_native.py first: '+filename)
    scene=validate_project(root,scene);options=load(root) if exclude_extensions is None and exclude_files is None else normalized(exclude_extensions,exclude_files)
    parent.mkdir(parents=True,exist_ok=True);stage=Path(tempfile.mkdtemp(prefix='.myengine-linux-',dir=parent))
    try:
        data=stage/'Data';data.mkdir();copy_project(root,data,progress,options);prepare_build_scenes(root,data);validate_project(data,scene)
        for p in engine.glob('engine_*.py'):shutil.copy2(p,data/p.name)
        shutil.copy2(engine/'PNGJSONUnitylity.py',data/'PNGJSONUnitylity.py');shutil.copytree(engine/'shaders',data/'shaders',dirs_exist_ok=True);shutil.copytree(native,data/'platforms/linux',dirs_exist_ok=True)
        set_allowed(data,allowed(root))
        from engine_releases import make_metadata
        metadata=make_metadata(root,name,scene,'linux-x64',release_options);metadata['experimental']=True
        (data/'build.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
        if not (data/'donation_access.json').exists():(data/'donation_access.json').write_text('{"unlockAll":false}',encoding='utf-8')
        (data/'run_game.py').write_text('from pathlib import Path\nimport json\nfrom engine_linux import run\nroot=Path(__file__).resolve().parent\nrun(root,json.loads((root/"build.json").read_text())["mainScene"])\n',encoding='utf-8')
        launcher=stage/'run.sh';launcher.write_text('#!/bin/sh\nset -eu\nMYENGINE_GAME_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\nexec python3 "$MYENGINE_GAME_DIR/Data/run_game.py"\n');launcher.chmod(0o755)
        (stage/'REQUIREMENTS.txt').write_text('Experimental Linux x86_64 player. Requires CPython 3.11–3.13, SDL2, desktop OpenGL 2.1+ and libstdc++.\nRun: sh run.sh\nSystem packages on Debian/Ubuntu: python3 libsdl2-2.0-0 libgl1 libstdc++6\nPython third-party modules used by your scripts must also be installed. Windows-only imports/DLLs need a Linux port.\nKernels can be rebuilt on your Linux distribution from the engine sources with tools/build_linux_native.py.\nThis package uses system Python; it is not a self-contained executable.\n',encoding='utf-8')
        stage.rename(destination);progress('Linux player exported: '+str(destination));return destination
    except BaseException:shutil.rmtree(stage,ignore_errors=True);raise

class PublicationError(RuntimeError):
    def __init__(self, build, error, stage='publication'):
        self.build=Path(build);self.retry_publication=stage=='publication'
        label='опубликовать на GitHub' if self.retry_publication else 'сохранить новую версию проекта'
        super().__init__('Сборка создана: '+str(build)+'\n\nНе удалось '+label+': '+str(error))

def export_target(target,engine_root,project_root,**kwargs):
    from engine_releases import load_settings,settings,publish_build,bump_version,save_settings,BuildVersionLock
    key=target.split()[0]
    if key in PORT_LIMITATIONS:raise NotImplementedError(PORT_LIMITATIONS[key])
    if key not in ('Windows','Linux'):raise ValueError('Unknown build target')
    expected=kwargs.pop('expected_version',None)
    with BuildVersionLock(project_root):
        if expected is not None and load_settings(project_root)['version']!=expected:
            raise RuntimeError('Версия проекта изменилась в другом окне. Открой окно сборки заново.')
        options=kwargs.get('release_options')
        options=load_settings(project_root) if options is None else settings(options)
        if options['autoIncrementVersion']:options=dict(options,version=bump_version(options['version']))
        kwargs['release_options']=options
        if key=='Windows':result=export_game(engine_root,project_root,**kwargs)
        else:result=export_linux(engine_root,project_root,**kwargs)
        # Commit only after the complete player folder exists; publication is a separate stage.
        try:save_settings(project_root,options)
        except Exception as ex:raise PublicationError(result,ex,'version') from ex
        kwargs.get('progress',lambda text:None)('Версия собрана: '+options['version'])
    if options['publishAfterBuild']:
        try:
            url=publish_build(result,options,kwargs.get('progress',lambda text:None))
            kwargs.get('progress',lambda text:None)('Опубликовано: '+str(url))
        except Exception as ex:raise PublicationError(result,ex) from ex
    return result
