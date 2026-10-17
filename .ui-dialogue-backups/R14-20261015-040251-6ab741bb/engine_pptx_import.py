"""Import a snapshot from an already running desktop PowerPoint (Windows).

Only Python's standard library and Windows PowerShell 5.1 are required.
The exporter never creates or quits PowerPoint and never edits the user's deck.
"""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from engine_ui import load_document, image_paths

_IMPORT_LOCK = threading.Lock()


def _powershell():
    if sys.platform != 'win32':
        raise RuntimeError('Этот импорт подключается к открытому PowerPoint в Windows. '
                           'Готовый интерфейс PNG/JSON работает без Office.')
    windows = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    for folder in ('Sysnative', 'System32'):
        path = windows/folder/'WindowsPowerShell/v1.0/powershell.exe'
        if path.is_file():
            return str(path)
    found = shutil.which('powershell.exe')
    if found:
        return found
    raise RuntimeError('Не найден Windows PowerShell 5.1 (powershell.exe). '
                       'Для этого импортера PowerShell 7 / pwsh не используется.')


def _decode_output(data):
    if not data:
        return ''
    try:
        return data.decode('utf-8-sig')
    except UnicodeDecodeError:
        import locale
        encoding = locale.getpreferredencoding(False)
        if sys.platform == 'win32':
            import ctypes
            encoding = 'cp'+str(ctypes.windll.kernel32.GetOEMCP())
        return data.decode(encoding, errors='replace')


def _run_export(source, stage, engine, timeout, *, include_background=False):
    script = engine/'tools/powerpoint_export.ps1'
    if not script.is_file():
        raise FileNotFoundError(script)
    command = [_powershell(), '-NoProfile', '-NonInteractive', '-STA',
               '-ExecutionPolicy', 'Bypass', '-File', str(script), '-Output', str(stage)]
    if source is not None:
        command.extend(['-Source', str(source)])
    if include_background:
        command.append('-IncludeBackground')
    kwargs = {'capture_output': True, 'timeout': timeout}
    if sys.platform == 'win32':
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(command, **kwargs)
    except subprocess.TimeoutExpired as exc:
        # run() kills only our PowerShell child. Never terminate POWERPNT.EXE.
        raise RuntimeError(f'PowerPoint не завершил экспорт за {timeout} секунд. '
                           'Проверьте, нет ли в PowerPoint диалога. Ваш PowerPoint не закрывался. '
                           'В нём могла остаться временная презентация MyEngine2-Export-*.pptx; '
                           'её можно закрыть без сохранения и повторить импорт.') from exc
    if result.returncode:
        detail = _decode_output(result.stderr or result.stdout)[-6000:]
        raise RuntimeError('Не удалось импортировать открытую презентацию. '
                           'Откройте нужную .pptx в обычном PowerPoint, затем переключитесь в редактор. '
                           'PowerPoint и редактор запускайте под одним пользователем с одинаковыми правами.\n\n'
                           + (detail or 'Код завершения: '+str(result.returncode)))
    return _decode_output(result.stderr).strip()


def _copy_frames(document, stage, source_dir):
    # Only explicit animation frames may come from the source directory.
    frames = {frame for slide in document['slides']
              for element in slide.get('elements', []) for frame in element.get('frames', [])}
    for relative in image_paths(document):
        image = (stage/relative).resolve()
        image.relative_to(stage)
        if image.is_file():
            continue
        if relative not in frames or source_dir is None:
            raise FileNotFoundError('Изображение UI отсутствует: '+relative)
        origin = (source_dir/relative).resolve()
        origin.relative_to(source_dir)
        if not origin.is_file():
            raise FileNotFoundError('Кадр анимации отсутствует: '+str(origin))
        image.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origin, image)


def has_backgrounds(path):
    """All slides have an actual cached background, including older imports."""
    path=Path(path).resolve();document=load_document(path)
    for slide in document['slides']:
        relative=slide.get('background')
        if not relative:return False
        image=(path.parent/relative).resolve();image.relative_to(path.parent)
        if not image.is_file():return False
    return True


def _export_stage(source,stage,engine,timeout,*,include_background=False):
    options={'include_background':True} if include_background else {}
    diagnostic=_run_export(source,stage,engine,timeout,**options)
    output=stage/'interface.ui.json';document=load_document(output)
    if include_background and any(not slide.get('background') for slide in document['slides']):
        raise RuntimeError('PowerPoint не экспортировал фон. Установи обновление R9 целиком и повтори импорт.')
    info_path=stage/'_powerpoint_source.json'
    info=json.loads(info_path.read_text(encoding='utf-8-sig'))
    folder=info.get('directory');source_dir=Path(folder).resolve() if folder else None
    _copy_frames(document,stage,source_dir)
    snapshot=stage/'_powerpoint_snapshot.pptx'
    if snapshot.exists():
        from engine_ui_effects import enrich_snapshot
        enrich_snapshot(snapshot,document)
        from engine_pptx_media import enrich_media
        enrich_media(snapshot,document,stage);snapshot.unlink()
    from engine_ui_content import media_paths
    for relative in media_paths(document):
        target=(stage/relative).resolve();target.relative_to(stage)
        if target.is_file():continue
        if source_dir is None:raise FileNotFoundError('Video file is missing: '+relative)
        origin=(source_dir/relative).resolve();origin.relative_to(source_dir)
        if not origin.is_file():raise FileNotFoundError('Video file is missing: '+relative)
        if origin.stat().st_size>1024**3:raise ValueError('Video limit: 1 GiB')
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(origin,target)
    info_path.unlink()
    if diagnostic:document.setdefault('warnings',[]).append(diagnostic[-4000:])
    if not info.get('source') and folder and document.get('sourcePresentation'):
        info['source']=str(Path(folder)/document['sourcePresentation'])
    return document,info


def _publish(source,root,target,engine_root,timeout,*,update=False,required=(),include_background=False):
    from datetime import datetime
    from uuid import uuid4
    from engine_scene import atomic_json
    from engine_ui_reimport import merge_document
    if not _IMPORT_LOCK.acquire(blocking=False):raise RuntimeError('Другой импорт PowerPoint ещё выполняется.')
    stage=None;backup=None;published=False;registry=root/'.myengine/ui-sources.json'
    try:
        registry_before=registry.read_bytes() if registry.exists() else None
        old=load_document(target) if update else None
        # Once requested, refresh cached backgrounds even while the scene hides
        # them. Turning the checkbox off must not delete the reusable images.
        include_background=bool(include_background or (old and any(s.get('background') for s in old['slides'])))
        target.parent.parent.mkdir(parents=True,exist_ok=True)
        stage=Path(tempfile.mkdtemp(prefix='.pptx-',dir=target.parent.parent)).resolve()
        document,info=_export_stage(source,stage,Path(engine_root or Path(__file__).parent).resolve(),timeout,
                                    include_background=include_background)
        if update:
            old=load_document(target)
            if source is None and old.get('sourcePresentation') and old['sourcePresentation']!=document.get('sourcePresentation'):
                raise ValueError('Открыта другая презентация. Выбери исходный PowerPoint-файл для обновления.')
            from engine_projects import project_scenes
            targets=set(tuple(t) for t in required)
            for scene in project_scenes(root):
                data=json.loads((root/scene).read_text(encoding='utf-8-sig'))
                if data.get('ui')!=target.relative_to(root).as_posix():continue
                targets.update((r['slide'],r['element']) for r in data.get('uiBlueprints',{}).values() if r.get('ui')==data['ui'])
            document=merge_document(old,document,targets)
            from engine_ui_content import media_paths
            managed=set(image_paths(old))|set(media_paths(old))|{target.name,'interface.ui.json'}
            required_assets=set(image_paths(document))|set(media_paths(document))
            for file in target.parent.rglob('*'):
                if not file.is_file():continue
                file.resolve().relative_to(target.parent)
                relative=file.relative_to(target.parent)
                if (relative.as_posix() not in managed or relative.as_posix() in required_assets) and not (stage/relative).exists():
                    (stage/relative).parent.mkdir(parents=True,exist_ok=True);shutil.copy2(file,stage/relative)
        output=stage/target.name
        if target.name!='interface.ui.json':(stage/'interface.ui.json').unlink()
        atomic_json(output,document);load_document(output)
        entries=json.loads(registry_before.decode('utf-8')) if registry_before else {}
        key=target.relative_to(root).as_posix()
        entries[key]={'source':info.get('source'),'presentation':document.get('sourcePresentation')}
        if update:
            backup=root/'.myengine/ui-backups'/(target.parent.name+'-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:8])
            backup.parent.mkdir(parents=True,exist_ok=True);target.parent.rename(backup)
        elif target.parent.exists():raise FileExistsError(target.parent)
        try:
            stage.rename(target.parent);published=True
            atomic_json(registry,entries)
        except BaseException:
            if published:shutil.rmtree(target.parent)
            if backup is not None:backup.rename(target.parent)
            if registry_before is None:registry.unlink(missing_ok=True)
            else:registry.write_bytes(registry_before)
            raise
        return target,document.get('warnings',[])
    finally:
        if stage is not None and stage.exists():shutil.rmtree(stage,ignore_errors=True)
        _IMPORT_LOCK.release()


def import_powerpoint(source,project_root,name,engine_root=None,*,timeout=300,include_background=False):
    from engine_projects import safe_name
    root=Path(project_root).resolve();target=root/'assets/ui'/safe_name(name)/'interface.ui.json'
    source=Path(source).resolve() if source is not None else None
    if source is not None and source.suffix.lower()!='.pptx':raise ValueError('Откройте презентацию формата .pptx')
    if target.parent.exists():raise FileExistsError('Папка UI уже существует. Используй «Обновить из PowerPoint».')
    return _publish(source,root,target,engine_root,timeout,include_background=include_background)


def update_powerpoint(path,project_root,source=None,engine_root=None,*,timeout=300,required=(),include_background=False):
    root=Path(project_root).resolve();target=(root/path).resolve();base=root/'assets/ui'
    target.parent.relative_to(base)
    if target.parent==base:raise ValueError('Выбери UI из отдельной папки assets/ui/<имя>.')
    load_document(target)
    registry=root/'.myengine/ui-sources.json'
    if source is None and registry.exists():
        entry=json.loads(registry.read_text(encoding='utf-8')).get(target.relative_to(root).as_posix(),{})
        source=entry.get('source')
    source=Path(source).resolve() if source else None
    if source is not None and source.suffix.lower()!='.pptx':raise ValueError('Выбери исходный .pptx')
    return _publish(source,root,target,engine_root,timeout,update=True,required=required,include_background=include_background)
