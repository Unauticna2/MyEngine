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


def _run_export(source, stage, engine, timeout):
    script = engine/'tools/powerpoint_export.ps1'
    if not script.is_file():
        raise FileNotFoundError(script)
    command = [_powershell(), '-NoProfile', '-NonInteractive', '-STA',
               '-ExecutionPolicy', 'Bypass', '-File', str(script), '-Output', str(stage)]
    if source is not None:
        command.extend(['-Source', str(source)])
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


def import_powerpoint(source, project_root, name, engine_root=None, *, timeout=300):
    """source=None imports ActivePresentation; a path selects that OPEN deck.

    Captures unsaved edits using SaveCopyAs. The resulting copy is the only
    presentation the exporter modifies/closes. No dependency installation.
    """
    from engine_projects import safe_name
    root = Path(project_root).resolve()
    target = root/'assets/ui'/safe_name(name)
    source = Path(source).resolve() if source is not None else None
    if source is not None and source.suffix.lower() != '.pptx':
        raise ValueError('Откройте презентацию формата .pptx')
    if target.exists():
        raise FileExistsError('Папка UI уже существует. Укажите новое имя ресурса.')
    if not _IMPORT_LOCK.acquire(blocking=False):
        raise RuntimeError('Другой импорт PowerPoint ещё выполняется.')
    stage = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix='.pptx-', dir=target.parent)).resolve()
        engine = Path(engine_root or Path(__file__).parent).resolve()
        diagnostic = _run_export(source, stage, engine, timeout)
        output = stage/'interface.ui.json'
        document = load_document(output)
        info_path = stage/'_powerpoint_source.json'
        info = json.loads(info_path.read_text(encoding='utf-8-sig'))
        folder = info.get('directory')
        source_dir = Path(folder).resolve() if folder else None
        _copy_frames(document, stage, source_dir)
        info_path.unlink()  # Do not publish the developer's local directory.
        warnings = document.setdefault('warnings', [])
        if diagnostic:
            warnings.append(diagnostic[-4000:])
        output.write_text(json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
        load_document(output)
        if target.exists():
            raise FileExistsError(target)
        stage.rename(target)
        return target/'interface.ui.json', warnings
    finally:
        if stage is not None and stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        _IMPORT_LOCK.release()
