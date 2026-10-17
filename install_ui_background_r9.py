"""Verified, reversible file update for MyEngine 2.5. Python standard library only."""
from pathlib import Path, PurePosixPath
import argparse
from datetime import datetime
import hashlib
import json
import os
import shutil
import sys
import tempfile
import uuid

VERSION = 'UI BACKGROUND R9'
BUNDLE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def destination(root, name):
    relative = PurePosixPath(name)
    if relative.is_absolute() or '..' in relative.parts or ':' in name or '\\' in name:
        raise ValueError('Invalid update path: '+name)
    path = root.joinpath(*relative.parts)
    path.resolve().relative_to(root)
    return path


def read_payload(bundle):
    manifest = json.loads((bundle/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('version') != VERSION or not isinstance(manifest.get('files'), dict):
        raise ValueError('Invalid R9 manifest. Extract the complete ZIP first.')
    payload = (bundle/'payload').resolve()
    for name, expected in manifest['files'].items():
        if digest(destination(payload,name)) != expected:
            raise ValueError('Update file is missing or damaged: '+name)
    return manifest


def verify(root, manifest):
    failed = [name for name, expected in manifest['files'].items()
              if not destination(root,name).is_file() or digest(destination(root,name)) != expected]
    if failed:
        raise RuntimeError('These files do not match R9:\n'+'\n'.join(failed))
    return len(manifest['files'])


def install(root, bundle=BUNDLE):
    root=Path(root).expanduser().resolve();bundle=Path(bundle).resolve()
    manifest=read_payload(bundle)
    if not (root/'MyEngine2Editor.py').is_file() or not (root/'start_editor.cmd').is_file():
        raise ValueError('Select the ENGINE folder containing MyEngine2Editor.py and start_editor.cmd.\n'
                         'Do not select the project or assets folder.\nSelected: '+str(root))
    runtime=root/'engine_runtime.py'
    if not runtime.is_file() or 'EngineGetRuntimeFlags' not in runtime.read_text(encoding='utf-8-sig'):
        raise ValueError('This patch requires MyEngine 2.5. Selected folder: '+str(root))
    paths={name:destination(root,name) for name in manifest['files']}
    for target in paths.values():
        if target.exists() and not target.is_file():raise ValueError('Not a regular file: '+str(target))
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]
    backup=root/'.ui-background-backups'/('R9-'+stamp)
    backup.mkdir(parents=True)
    stage=Path(tempfile.mkdtemp(prefix='.ui-background-r9-',dir=root))
    existed={};changed=[]
    try:
        # Complete payload validation, staging and backup before the first edit.
        for name,target in paths.items():
            saved=destination(backup,name);staged=destination(stage,name)
            staged.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(destination(bundle/'payload',name),staged)
            existed[name]=target.exists()
            if existed[name]:
                saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,saved)
        for name,target in paths.items():
            target.parent.mkdir(parents=True,exist_ok=True)
            os.replace(destination(stage,name),target);changed.append(name)
        count=verify(root,manifest)
    except BaseException:
        errors=[]
        for name in reversed(changed):
            try:
                if existed[name]:shutil.copy2(destination(backup,name),paths[name])
                else:paths[name].unlink(missing_ok=True)
            except OSError as error:errors.append(str(error))
        if errors:raise RuntimeError('Rollback needs attention. Backup: '+str(backup)+'\n'+'\n'.join(errors))
        raise
    finally:shutil.rmtree(stage,ignore_errors=True)
    # Only caches of replaced modules, never user source files or project data.
    for name,target in paths.items():
        if target.suffix != '.py':continue
        candidates=list((target.parent/'__pycache__').glob(target.stem+'.*.pyc'))
        candidates.append(target.with_suffix('.pyc'))
        for cache in candidates:
            try:cache.unlink(missing_ok=True)
            except OSError:pass
    report={'version':VERSION,'engine':str(root),'verified_files':count,'backup':str(backup),
            'files':manifest['files'],'restart_required':True}
    (root/'UI_BACKGROUND_R9_install_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


def initial_folder():
    known=Path(r'F:\Users\User\Desktop\MyEngine')
    for p in (known,Path.home()/'Desktop/MyEngine',Path.cwd(),BUNDLE.parent):
        if (p/'MyEngine2Editor.py').is_file():return p
    return Path.home()


def main():
    parser=argparse.ArgumentParser(description='Install/verify MyEngine UI BACKGROUND R9')
    parser.add_argument('--target',type=Path)
    parser.add_argument('--verify-only',action='store_true')
    args=parser.parse_args();window=None
    try:
        target=args.target
        if target is None:
            import tkinter as tk
            from tkinter import filedialog,messagebox
            window=tk.Tk();window.withdraw()
            messagebox.showinfo(VERSION,'Закройте MyEngine Editor, Hub и окно игры/Viewport.\n'
                'Затем выберите папку движка с MyEngine2Editor.py.\n'
                'PowerPoint закрывать не нужно.',parent=window)
            selected=filedialog.askdirectory(title='UI BACKGROUND R9 — выберите папку ДВИЖКА (MyEngine2Editor.py)',
                                              initialdir=str(initial_folder()),mustexist=True,parent=window)
            if not selected:return 1
            target=Path(selected)
        target=target.expanduser().resolve()
        if args.verify_only:
            count=verify(target,read_payload(BUNDLE))
            text=f'{VERSION}: verified {count} files.\nEngine: {target}'
        else:
            report=install(target)
            text=(f'{VERSION}: установлено и проверено {report["verified_files"]} файлов.\n'
                  f'Движок: {target}\n\n'
                  f'Запустите именно {target / "start_editor.cmd"}\n'
                  'Исправлены загрузка фона и повторное включение галочки.\n'
                  'Откройте исходный PowerPoint и выключите/включите галочку фона.\nНедостающий фон загрузится автоматически. Пересборка EXE не нужна.\n\n'
                  f'Резервная копия: {report["backup"]}')
        print(text)
        if window is not None:messagebox.showinfo(VERSION,text,parent=window)
        return 0
    except Exception as error:
        print('INSTALL FAILED: '+str(error),file=sys.stderr)
        if window is not None:
            from tkinter import messagebox
            messagebox.showerror(VERSION,str(error),parent=window)
        return 1
    finally:
        if window is not None:window.destroy()

if __name__=='__main__':raise SystemExit(main())
