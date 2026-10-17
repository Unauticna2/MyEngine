"""Opt-in release uploads and restoration into a separate folder. Standard library only."""
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.request import Request, urlopen
from urllib.parse import quote, urlsplit
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
from engine_scene import atomic_json
from engine_version import ENGINE_VERSION, ENGINE_BUILD, new_build_id

SETTINGS = 'release-settings.json'
MAX_ARCHIVE = 2 * 1024**3 - 1
MAX_EXPANDED = 16 * 1024**3
REPO_PATTERN = r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9_.-]{1,100}'

def repository(value):
    value = str(value).strip()
    if not re.fullmatch(REPO_PATTERN, value) or value.split('/')[1] in ('.','..'):
        raise ValueError('Укажи GitHub-репозиторий в формате автор/репозиторий.')
    return value

def bump_version(version):
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]+){0,5}',version):
        raise ValueError('Автоверсия: используй числовую версию, например 0.1.0, или отключи повышение.')
    parts=version.split('.')
    if any(len(p)>9 for p in parts):raise ValueError('Version component is too large')
    parts[-1]=str(int(parts[-1])+1)
    return '.'.join(parts)

class BuildVersionLock:
    """OS lock is released after a crash too; protects simultaneous Hub/editor builds."""
    def __init__(self,root):self.path=Path(root)/'.myengine/build-version.lock';self.file=None
    def __enter__(self):
        self.path.parent.mkdir(parents=True,exist_ok=True);self.file=self.path.open('a+b')
        try:
            if os.name=='nt':
                import msvcrt
                if self.file.seek(0,2)==0:self.file.write(b'0');self.file.flush()
                self.file.seek(0);msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close();raise RuntimeError('Этот проект уже собирается в другом окне. Дождись завершения.') from None
        return self
    def __exit__(self,*unused):
        if os.name=='nt':
            import msvcrt
            self.file.seek(0);msvcrt.locking(self.file.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            fcntl.flock(self.file,fcntl.LOCK_UN)
        self.file.close()

def settings(value=None):
    value = {} if value is None else value
    if not isinstance(value, dict):raise ValueError('release-settings.json must be an object')
    enabled = value.get('publishAfterBuild', False)
    if type(enabled) is not bool:raise ValueError('publishAfterBuild must be true or false')
    repo = str(value.get('repository','')).strip()
    if repo:repo = repository(repo)
    if enabled and not repo:raise ValueError('Для автопубликации укажи репозиторий.')
    version = str(value.get('version','0.1.0')).strip()
    if not version or len(version)>80 or any(ord(c)<32 for c in version):raise ValueError('Invalid game version')
    automatic=value.get('autoIncrementVersion',True)
    if type(automatic) is not bool:raise ValueError('autoIncrementVersion must be true or false')
    if automatic:bump_version(version)
    return {'repository':repo, 'version':version, 'publishAfterBuild':enabled,'autoIncrementVersion':automatic}

def load_settings(root):
    p=Path(root)/SETTINGS
    return settings(json.loads(p.read_text(encoding='utf-8-sig')) if p.exists() else None)

def save_settings(root, value):
    value=settings(value);atomic_json(Path(root)/SETTINGS,value);return value

def make_metadata(root, name, scene, target, options=None):
    options=load_settings(root) if options is None else settings(options)
    build_id=new_build_id()
    result={'engineVersion':ENGINE_VERSION,'engineBuild':ENGINE_BUILD,'name':name,
            'version':options['version'],'mainScene':scene,'target':target,
            'buildId':build_id,'createdUtc':datetime.now(timezone.utc).isoformat()}
    if options['repository']:
        slug=re.sub(r'[^A-Za-z0-9_.-]','_',name)[:60] or 'game'
        prefix='MyEngine-'+slug+'-'+target+'-'
        result['release']={'repository':options['repository'],'tag':'build-'+build_id,
                           'asset':prefix+build_id+'.zip','assetPrefix':prefix}
    return result

def gh_executable():
    p=shutil.which('gh')
    if not p:
        candidate=Path(os.environ.get('ProgramFiles','C:/Program Files'))/'GitHub CLI/gh.exe'
        if candidate.is_file():p=str(candidate)
    if not p:raise RuntimeError('Установи GitHub CLI: https://cli.github.com/ и выполни gh auth login. Сборка сохранена локально.')
    return p

def gh_run(args, timeout=600):
    done=subprocess.run([gh_executable(),*args],capture_output=True,text=True,encoding='utf-8',errors='replace',
                        timeout=timeout,creationflags=0x08000000 if os.name=='nt' else 0)
    if done.returncode:raise RuntimeError((done.stderr or done.stdout or 'GitHub CLI error').strip()[-6000:])
    return done.stdout.strip()

def publish_build(build, options, progress=lambda text:None):
    options=settings(options)
    if not options['publishAfterBuild']:
        return None
    build=Path(build).resolve()
    info=json.loads((build/'Data/build.json').read_text(encoding='utf-8-sig'))
    release=info.get('release',{})
    if release.get('repository')!=options['repository']:raise ValueError('Build repository differs from the authorized publication settings')
    repo=repository(options['repository']);tag=release['tag'];asset=release['asset']
    # Upload only the exported player folder, never the source project or its credentials.
    progress('GitHub: проверка входа и репозитория…')
    gh_run(['auth','status','--hostname','github.com'],timeout=30)
    gh_run(['api','repos/'+repo,'--hostname','github.com'],timeout=30)
    existing=None
    try:
        existing=json.loads(gh_run(['api','repos/'+repo+'/releases/tags/'+quote(tag,safe=''),'--hostname','github.com'],timeout=30))
    except RuntimeError as ex:
        if '404' not in str(ex):raise
    if existing is not None:
        marker='Build: '+info['buildId']+'\n'
        if marker not in (existing.get('body','')+'\n'):
            raise ValueError('Тег уже занят другим релизом; он не будет заменён: '+tag)
        uploaded=next((x for x in existing.get('assets',[]) if x.get('name')==asset and x.get('state')=='uploaded'),None)
        if not existing.get('draft'):
            if uploaded:return existing['html_url']
            raise ValueError('Опубликованный релиз не содержит ZIP. Проверь релиз в GitHub: '+tag)
        if uploaded:
            gh_run(['release','edit',tag,'--repo','github.com/'+repo,'--draft=false','--latest=false'])
            return existing['html_url']
    with tempfile.TemporaryDirectory(prefix='myengine-publish-') as folder:
        archive=Path(folder)/asset
        progress('GitHub: упаковка готовой игры…')
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            for path in sorted(build.rglob('*')):
                if path.is_symlink():raise ValueError('Build archive cannot contain symlinks: '+str(path))
                if path.is_file():z.write(path,path.relative_to(build).as_posix())
        if archive.stat().st_size>MAX_ARCHIVE:raise ValueError('ZIP превышает лимит одного release asset (2 GiB). Сборка сохранена локально.')
        notes=Path(folder)/'notes.txt'
        notes.write_text(f"{info['name']} {info['version']}\nBuild: {info['buildId']}\nEngine: {info['engineBuild']}\nTarget: {info['target']}\n\nDownload {asset}; unpack the complete folder.\n",encoding='utf-8')
        progress('GitHub: загрузка '+asset+'…')
        if existing is not None:
            # Resume only this build's incomplete draft, after an explicit retry.
            gh_run(['release','upload',tag,str(archive),'--repo','github.com/'+repo,'--clobber'],timeout=3600)
            gh_run(['release','edit',tag,'--repo','github.com/'+repo,'--draft=false','--latest=false'])
            return existing['html_url']
        # gh creates a draft, uploads the asset, then publishes. Never overwrite a published tag.
        return gh_run(['release','create',tag,str(archive),'--repo','github.com/'+repo,
                       '--title',f"{info['name']} {info['version']} · {info['buildId']}",
                       '--notes-file',str(notes),'--latest=false'],timeout=3600)

def api_json(path):
    req=Request('https://api.github.com/'+path,headers={'Accept':'application/vnd.github+json',
                'User-Agent':'MyEngine/'+ENGINE_VERSION,'X-GitHub-Api-Version':'2022-11-28'})
    with urlopen(req,timeout=30) as response:raw=response.read(8*1024*1024+1)
    if len(raw)>8*1024*1024:raise ValueError('GitHub response too large')
    return json.loads(raw)

def recovery_config(root):
    from engine_version import read_info
    info=read_info(root)
    if info.get('release'):return info['release']
    p=Path(root)/'engine-release.json'
    return json.loads(p.read_text(encoding='utf-8-sig')) if p.exists() else {'repository':'','tag':'','asset':''}

def list_releases(repo, prefix=''):
    repo=repository(repo);out=[]
    # Latest 100 releases; an exact older tag is also accepted by the restore API/dialog.
    for item in api_json('repos/'+repo+'/releases?per_page=100'):
        if item.get('draft'):continue
        for asset in item.get('assets',[]):
            name=asset.get('name','')
            if name.endswith('.zip') and name.startswith(prefix):
                out.append({'tag':item['tag_name'],'asset':name,'title':item.get('name') or item['tag_name']})
    return out

def extract_archive(archive, parent, name):
    """Archive path safety only. Does not scan/hash the installed game."""
    parent=Path(parent).expanduser().resolve();parent.mkdir(parents=True,exist_ok=True)
    name=re.sub(r'[^A-Za-z0-9_.-]','_',name)[:110].strip('.') or 'restored'
    destination=parent/name
    if destination.exists():destination=parent/(name+'-'+new_build_id())
    stage=Path(tempfile.mkdtemp(prefix='.restore-',dir=parent))
    try:
        with zipfile.ZipFile(archive) as z:
            members=z.infolist()
            if len(members)>200000 or sum(x.file_size for x in members)>MAX_EXPANDED:raise ValueError('Archive expansion limit exceeded')
            required=sum(x.file_size for x in members)
            if shutil.disk_usage(parent).free<required+64*1024**2:raise OSError('Недостаточно места для распаковки.')
            seen=set()
            for item in members:
                raw=item.filename.replace('\\','/')
                p=PurePosixPath(raw)
                if p.is_absolute() or not p.parts or any(v in ('..','.') or ':' in v or v.endswith((' ','.')) or
                    re.fullmatch(r'(?i)(con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\..*)?',v) for v in p.parts):
                    raise ValueError('Unsafe ZIP path: '+raw)
                mode=item.external_attr>>16
                if stat.S_ISLNK(mode) or stat.S_IFMT(mode) not in (0,stat.S_IFREG,stat.S_IFDIR):raise ValueError('ZIP links/devices are not supported')
                key=p.as_posix().casefold()
                if key in seen:raise ValueError('Duplicate ZIP path: '+raw)
                seen.add(key)
                target=stage.joinpath(*p.parts)
                if item.is_dir():target.mkdir(parents=True,exist_ok=True);continue
                target.parent.mkdir(parents=True,exist_ok=True)
                with z.open(item) as source,target.open('xb') as dest:shutil.copyfileobj(source,dest,1024*1024)
                if os.name!='nt' and mode&0o111:target.chmod(0o755)
        stage.rename(destination)
        return destination
    except BaseException:
        shutil.rmtree(stage,ignore_errors=True);raise

def restore_release(repo, tag, asset, parent, progress=lambda text:None):
    repo=repository(repo)
    if not tag or len(tag)>255:raise ValueError('Укажи точный тег релиза.')
    release=api_json('repos/'+repo+'/releases/tags/'+quote(tag,safe=''))
    match=next((x for x in release.get('assets',[]) if x.get('name')==asset),None)
    if match is None:raise ValueError('Этот ZIP отсутствует в выбранном релизе: '+asset)
    if match.get('size',0)>MAX_ARCHIVE:raise ValueError('Archive exceeds 2 GiB')
    url=match['browser_download_url'];parts=urlsplit(url)
    if parts.scheme!='https' or parts.hostname!='github.com':raise ValueError('Unexpected GitHub asset URL')
    with tempfile.TemporaryDirectory(prefix='myengine-download-') as folder:
        archive=Path(folder)/'game.zip';received=0
        progress('Скачивание '+tag+' / '+asset+'…')
        with urlopen(Request(url,headers={'User-Agent':'MyEngine/'+ENGINE_VERSION}),timeout=60) as src,archive.open('wb') as dest:
            if urlsplit(src.geturl()).scheme!='https':raise ValueError('Non-HTTPS asset redirect')
            while True:
                chunk=src.read(1024*1024)
                if not chunk:break
                received+=len(chunk)
                if received>MAX_ARCHIVE:raise ValueError('Archive exceeds 2 GiB')
                dest.write(chunk)
                progress('Скачано '+str(received//(1024*1024))+' MiB — '+tag)
        if match.get('size') is not None and received!=match['size']:raise ValueError('Загрузка оборвалась; повтори попытку.')
        progress('Распаковка '+tag+'…')
        return extract_archive(archive,parent,repo.split('/')[1]+'-'+tag)
