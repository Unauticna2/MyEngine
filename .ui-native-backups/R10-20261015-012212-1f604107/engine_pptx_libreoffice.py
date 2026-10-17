"""PPTX -> layered PNG/JSON UI through LibreOffice, without Microsoft Office.
Optional pypdfium2/Pillow dependencies are needed only during asset import.
"""
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import threading
from engine_ui import load_document, image_paths, validate
from engine_pptx_layers import prepare_layers

_PDF_LOCK = threading.Lock()  # PDFium is not thread-safe.


def libreoffice_config():
    return Path(os.environ.get('LOCALAPPDATA', Path.home()/'.local/share'))/'MyEngine2Hub/libreoffice.json'


def save_libreoffice_path(path):
    exe = Path(path).expanduser().resolve()
    if not exe.is_file():
        raise FileNotFoundError(exe)
    target = libreoffice_config()
    target.parent.mkdir(parents=True, exist_ok=True)
    from engine_scene import atomic_json
    atomic_json(target, {'executable': str(exe)})


def find_libreoffice(explicit=None):
    if explicit:
        p = Path(explicit).expanduser()
        if not p.is_file():
            raise FileNotFoundError(p)
        return str(p.resolve())
    candidates = []
    if os.environ.get('MYENGINE_LIBREOFFICE'):
        candidates.append(os.environ['MYENGINE_LIBREOFFICE'])
    try:
        candidates.append(json.loads(libreoffice_config().read_text(encoding='utf-8')).get('executable', ''))
    except (OSError, ValueError, AttributeError):
        pass
    for variable in ('ProgramFiles', 'ProgramFiles(x86)', 'ProgramW6432'):
        if os.environ.get(variable):
            base = Path(os.environ[variable])/'LibreOffice/program'
            candidates.extend([str(base/'soffice.com'), str(base/'soffice.exe')])
    for name in ('soffice.com', 'soffice', 'libreoffice', 'soffice.exe'):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    candidates.append('/Applications/LibreOffice.app/Contents/MacOS/soffice')
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    raise RuntimeError('LibreOffice не найден. Установите LibreOffice с https://www.libreoffice.org/download/download-libreoffice/ '
                       'или нажмите «LibreOffice executable…» и укажите program/soffice.com (либо soffice.exe).')


def _dependencies():
    try:
        import pypdfium2
        from PIL import Image, ImageChops
    except ImportError as exc:
        raise RuntimeError('Для импорта нужны pypdfium2 и Pillow. Запустите setup_libreoffice.cmd '
                           'из папки движка. Игрокам эти пакеты не нужны.') from exc
    return pypdfium2, Image, ImageChops


def _recover_sprite(black, white):
    """Recover straight RGBA from two opaque renders, including white objects."""
    from PIL import Image, ImageChops
    if black.size != white.size:
        raise ValueError('LibreOffice matte page sizes differ')
    diff = ImageChops.subtract(white.convert('RGB'), black.convert('RGB'))
    r, g, b = diff.split()
    alpha = ImageChops.invert(ImageChops.lighter(ImageChops.lighter(r, g), b))
    bbox = alpha.getbbox()
    if bbox is None:
        return Image.new('RGBA', (1, 1)), None
    rgb = black.convert('RGB').crop(bbox).tobytes()
    aa = alpha.crop(bbox).tobytes()
    pixels = bytearray(4*len(aa))
    for i, a in enumerate(aa):
        if a:
            src, dst = i*3, i*4
            pixels[dst] = min(255, (rgb[src]*255+a//2)//a)
            pixels[dst+1] = min(255, (rgb[src+1]*255+a//2)//a)
            pixels[dst+2] = min(255, (rgb[src+2]*255+a//2)//a)
            pixels[dst+3] = a
    return Image.frombytes('RGBA', (bbox[2]-bbox[0], bbox[3]-bbox[1]), bytes(pixels)), bbox


def _render_pdf(path, tasks, document, output):
    pdfium, _, _ = _dependencies()
    scale = min(2., 2560/max(document['width'], document['height']))
    with _PDF_LOCK:
        pdf = pdfium.PdfDocument(str(path))
        try:
            if len(pdf) != len(tasks):
                raise RuntimeError(f'LibreOffice exported {len(pdf)} pages; expected {len(tasks)}. No partial UI was imported.')
            black = None
            for index, task in enumerate(tasks):
                page = pdf[index]
                try:
                    bitmap = page.render(scale=scale, fill_color=(255,255,255,255))
                    try:
                        image = bitmap.to_pil().convert('RGB')
                    finally:
                        bitmap.close()
                finally:
                    page.close()
                if task['type'] == 'background':
                    image.save(output/task['file'], format='PNG')
                elif task['type'] == 'black':
                    black = image
                else:
                    sprite, bounds = _recover_sprite(black, image)
                    item = task['element']
                    if bounds:
                        x, y, _, _ = item['rect']
                        item['imageRect'] = [bounds[0]/scale-x, bounds[1]/scale-y,
                                             sprite.width/scale, sprite.height/scale]
                    sprite.save(output/item['image'], format='PNG')
                    black = None
        finally:
            pdf.close()


def _convert(soffice, deck, work, timeout):
    profile = work/'profile'
    profile.mkdir()
    user = profile/'user'
    user.mkdir()
    # Private profile prevents reuse of an open LibreOffice window.
    (user/'registrymodifications.xcu').write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<oor:items xmlns:oor="http://openoffice.org/2001/registry">'
        '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
        '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>'
        '</item></oor:items>', encoding='utf-8')
    options = json.dumps({'ExportHiddenSlides': {'type': 'boolean', 'value': 'true'},
                          'ExportNotesPages': {'type': 'boolean', 'value': 'false'}})
    command = [soffice, '-env:UserInstallation='+profile.as_uri(), '--headless',
               '--nologo', '--nodefault', '--norestore', '--convert-to',
               'pdf:impress_pdf_Export:'+options, '--outdir', str(work), str(deck)]
    kwargs = {'stdout': subprocess.PIPE, 'stderr': subprocess.PIPE}
    if os.name == 'nt':
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs['start_new_session'] = True
    process = subprocess.Popen(command, **kwargs)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        # Terminate only this isolated converter tree, never unrelated office windows.
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            import signal
            try:os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:pass
        process.kill()
        process.communicate()
        raise RuntimeError(f'LibreOffice не завершил импорт за {timeout} секунд. '
                           'Попробуйте разделить презентацию на несколько файлов.') from exc
    pdf = work/(deck.stem+'.pdf')
    if process.returncode or not pdf.is_file():
        details = (stderr+stdout).decode('utf-8', errors='replace')[:5000]
        raise RuntimeError('LibreOffice не создал PDF для импорта.\n'+details)
    return pdf


def import_powerpoint(source, project_root, name, engine_root=None, *, libreoffice=None, timeout=300):
    """Keep the editor API; use LibreOffice only. The source file is never saved."""
    from engine_projects import safe_name
    source = Path(source).resolve()
    root = Path(project_root).resolve()
    if source.suffix.lower() != '.pptx':
        raise ValueError('Select a .pptx file')
    if not source.is_file():
        raise FileNotFoundError(source)
    target = root/'assets/ui'/safe_name(name)
    if target.exists():
        raise FileExistsError('Choose a new UI asset name; this folder already exists')
    soffice = find_libreoffice(libreoffice)
    _dependencies()
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.pptx-', dir=target.parent))
    try:
        with tempfile.TemporaryDirectory(prefix='myengine-lo-') as temp:
            work = Path(temp).resolve()
            deck = work/'layers.pptx'
            document, tasks = prepare_layers(source, deck)
            validate(document)
            pdf = _convert(soffice, deck, work, timeout)
            _render_pdf(pdf, tasks, document, stage)
        for image in image_paths(document):
            path = (stage/image).resolve()
            path.relative_to(stage)
            if not path.is_file():
                origin = (source.parent/image).resolve()
                origin.relative_to(source.parent)
                if not origin.is_file():
                    raise FileNotFoundError(f'UI frame image is missing: {image}')
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(origin, path)
        output = stage/'interface.ui.json'
        output.write_text(json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
        load_document(output)
        stage.rename(target)
        return target/'interface.ui.json', document['warnings']
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
