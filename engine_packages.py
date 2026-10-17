"""Public GitHub package discovery, staging, new-repository publishing and cloning.
No project is published or executed by discovery. Authentication belongs to gh CLI.
"""
from pathlib import Path
from urllib.parse import urlencode,quote
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import hashlib,html,json,os,re,shutil,subprocess,tempfile,zipfile
from engine_projects import inside,safe_name,read_project,PROJECT_FILE
from engine_scene import atomic_json

PREFIXES=('mypackege_','mypakege_')
QUERIES=('topic:mypakege','MyPakege_ in:name','MyPackege_ in:name')
MAX_FILE=90*1024*1024;MAX_TOTAL=500*1024*1024
SKIP_DIRS={'.git','.myengine','.venv','venv','node_modules','__pycache__','build','builds','legacy','python','tests'}
EXTENSIONS={'.py','.json','.obj','.4d','.vox','.png','.bmp','.jpg','.jpeg','.ico','.txt','.md','.wav','.ogg','.mp3','.mp4','.mtl','.vert','.frag'}


def executable(name):
    found=shutil.which(name)
    if found:return found
    if os.name=='nt':
        candidates={'git':[Path(os.environ.get('ProgramFiles','C:/Program Files'))/'Git/cmd/git.exe'],
                    'gh':[Path(os.environ.get('ProgramFiles','C:/Program Files'))/'GitHub CLI/gh.exe']}
        for p in candidates.get(name,[]):
            if p.is_file():return str(p)
    return None

def run(args,cwd=None,timeout=120,input_text=None):
    env=os.environ.copy();env['GIT_TERMINAL_PROMPT']='0';env['GH_PROMPT_DISABLED']='1';env['GH_HOST']='github.com'
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    r=subprocess.run([str(x) for x in args],cwd=cwd,input=input_text,text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout,env=env,creationflags=flags)
    if r.returncode:raise RuntimeError((r.stderr or r.stdout or 'Command failed').strip()[-4000:])
    return r.stdout.strip()

def http_bytes(url,limit=2*1024*1024):
    # All callers construct URLs under GitHub's public API/raw hosts.
    if not url.startswith(('https://api.github.com/','https://raw.githubusercontent.com/')):raise ValueError('Unsupported package host')
    request=Request(url,headers={'User-Agent':'MyEngine2-PackageHub/2.3','Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'})
    try:
        with urlopen(request,timeout=20) as response:
            size=response.headers.get('Content-Length')
            if size and int(size)>limit:raise ValueError('Remote file exceeds preview size limit')
            data=response.read(limit+1)
            if len(data)>limit:raise ValueError('Remote file exceeds preview size limit')
            return data
    except HTTPError as ex:
        if ex.code in (403,429):raise RuntimeError('GitHub rate limit or access denied. Wait and retry; public search allows a limited number of requests.') from ex
        raise

def valid_repo(value):
    if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9_.-]{1,100}',value):raise ValueError('Expected OWNER/REPOSITORY')
    return value

def search_page(query_index=0,page=1,author=''):
    if not 0<=query_index<len(QUERIES) or not 1<=page<=10:raise ValueError('Invalid search page')
    query=QUERIES[query_index]
    if author:
        if not re.fullmatch(r'[A-Za-z0-9-]{1,39}',author):raise ValueError('Invalid GitHub author')
        query+=' user:'+author
    url='https://api.github.com/search/repositories?'+urlencode({'q':query,'per_page':100,'page':page,'sort':'updated','order':'desc'})
    raw=json.loads(http_bytes(url,8*1024*1024));items=[]
    for r in raw.get('items',[]):
        if not (r.get('name','').lower().startswith(PREFIXES) or 'mypakege' in r.get('topics',[])):continue
        full=valid_repo(r['full_name'])
        items.append({'full_name':full,'description':r.get('description') or '', 'branch':r['default_branch'],'url':'https://github.com/'+full,'stars':r.get('stargazers_count',0)})
    return {'items':items,'total':raw.get('total_count',0),'incomplete':raw.get('incomplete_results',False),'more':page*100<min(1000,raw.get('total_count',0))}

def package_details(repo):
    full=valid_repo(repo['full_name']);branch=quote(repo['branch'],safe='');base='https://raw.githubusercontent.com/'+full+'/'+branch+'/'
    description=repo.get('description','');preview=None
    for name in ('Data.txt','Дата.txt'):
        try:description=http_bytes(base+quote(name),128*1024).decode('utf-8-sig',errors='replace');break
        except HTTPError as ex:
            if ex.code!=404:raise
    for name in ('image.png','имадж.png','Image.png'):
        try:
            data=http_bytes(base+quote(name),8*1024*1024)
            if data[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('Preview must be PNG')
            # Tk image decoding stays on the UI thread; bound both bytes and dimensions.
            import struct
            width,height=struct.unpack('>II',data[16:24])
            if not 1<=width<=4096 or not 1<=height<=4096:raise ValueError('Preview dimensions exceed 4096')
            preview=data;break
        except HTTPError as ex:
            if ex.code!=404:raise
    return description,preview

def package_files(root):
    root=Path(root).resolve();files=[];total=0
    for base,dirs,names in os.walk(root):
        dirs[:]=[d for d in dirs if not d.startswith('.') and d.lower() not in SKIP_DIRS and not (Path(base)/d).is_symlink()]
        for name in names:
            p=Path(base)/name;rel=p.relative_to(root)
            if p.is_symlink() or name.startswith('.') or p.suffix.lower() not in EXTENSIONS:continue
            if name.lower() in ('python.ini','engine.log','data.txt','package.json','package.zip','image.png','index.html'):continue
            if name.lower().startswith(('credentials','secrets','private_key')):continue
            if len(rel.parts)==1 and (name.startswith(('engine_','MyEngine')) or name in ('setup_python.py','launch_editor.py')):continue
            # An explicit file review is presented before publishing this candidate list.
            size=p.stat().st_size
            if size>MAX_FILE:raise ValueError('GitHub package file is too large: '+str(rel))
            total+=size
            if total>MAX_TOTAL:raise ValueError('Package exceeds 500 MiB; remove builds or large media')
            files.append((rel.as_posix(),size))
    return sorted(files)

def repo_name(name):
    if not name.lower().startswith(PREFIXES):name='MyPackege_'+name
    if not re.fullmatch(r'My(?:Packege|Pakege)_[A-Za-z0-9_.-]{1,70}',name,re.I):raise ValueError('Package name: Latin letters, digits, _, - and .')
    return name

def prepare_package(root,staging,name,scene,description,preview,selected=None):
    from engine_build import validate_project
    root=Path(root).resolve();staging=Path(staging).resolve();name=repo_name(name)
    if staging.exists():raise FileExistsError('Choose a new package staging folder')
    if staging==root or root.is_relative_to(staging):raise ValueError('Staging cannot contain the project')
    validate_project(root,scene)
    candidates=dict(package_files(root));names=list(candidates) if selected is None else list(selected)
    if any(n not in candidates for n in names):raise ValueError('Selected file is not a project candidate')
    image=Path(preview).read_bytes()
    if not image.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('Select a PNG preview image')
    if len(image)>8*1024*1024:raise ValueError('Preview exceeds 8 MiB')
    staging.mkdir(parents=True)
    try:
        for n in names:
            src=inside(root,n);dst=inside(staging,n);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
        project=json.loads((staging/PROJECT_FILE).read_text(encoding='utf-8-sig')) if (staging/PROJECT_FILE).exists() else {'format':1}
        project.update(name=name,engineVersion='2.3',mainScene=scene);atomic_json(staging/PROJECT_FILE,project)
        # Catch unchecked dependencies before any remote write.
        read_project(staging);validate_project(staging,scene)
        (staging/'image.png').write_bytes(image);(staging/'Data.txt').write_text(description,encoding='utf-8')
        hashes=[{'path':p.relative_to(staging).as_posix(),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(staging.rglob('*')) if p.is_file()]
        atomic_json(staging/'package.json',{'format':1,'engine':'MyEngine 2','engineVersion':'2.3','name':name,'scene':scene,'files':hashes})
        with zipfile.ZipFile(staging/'package.zip','w',zipfile.ZIP_DEFLATED) as z:
            for p in sorted(staging.rglob('*')):
                if p.is_file() and p.name!='package.zip':z.write(p,p.relative_to(staging).as_posix())
        if (staging/'package.zip').stat().st_size>MAX_FILE:raise ValueError('package.zip exceeds 90 MiB; reduce this package before publishing')
        title=html.escape(name);desc=html.escape(description)
        (staging/'index.html').write_text('<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>'+title+'</title><style>body{max-width:850px;margin:50px auto;padding:20px;background:#111b29;color:#d9e6f8;font:18px system-ui}img{max-width:100%;max-height:420px}a{color:#7de0cb}pre{white-space:pre-wrap}</style><h1>'+title+'</h1><img src="image.png" alt="Preview"><pre>'+desc+'</pre><p><a href="package.zip">Download MyEngine project</a></p></html>',encoding='utf-8')
        (staging/'.nojekyll').touch()
        return {'path':str(staging),'name':name,'files':hashes,'bytes':sum(x['bytes'] for x in hashes)}
    except BaseException:shutil.rmtree(staging,ignore_errors=True);raise

def publish_new(staging,owner='',progress=lambda text:None):
    root=Path(staging).resolve();meta=json.loads((root/'package.json').read_text());name=repo_name(meta['name'])
    git=executable('git');gh=executable('gh')
    if not git:raise RuntimeError('Install Git for Windows, then restart the Hub')
    if not gh:raise RuntimeError('Install GitHub CLI (gh), then use Login to GitHub')
    run([gh,'auth','status','--hostname','github.com'])
    login=run([gh,'api','user','--jq','.login']);owner=owner.strip() or login;full=valid_repo(owner+'/'+name)
    # Only a NEW repository. Never force-push or overwrite an existing remote.
    if (root/'.git').exists():raise ValueError('This staging folder was already used. Check GitHub before retrying; prepare a new package.')
    progress('Creating local commit…');run([git,'init','-b','main'],root)
    run([git,'config','user.name',login],root);run([git,'config','user.email',login+'@users.noreply.github.com'],root)
    run([git,'add','--all'],root);run([git,'commit','-m','Publish MyEngine package'],root)
    # Scoped credential helper: no token in source, URL, gitconfig or command output.
    run([git,'config','credential.https://github.com.helper',''],root)
    helper='!"'+gh.replace('\\','/')+'" auth git-credential'
    run([git,'config','--add','credential.https://github.com.helper',helper],root)
    progress('Creating PUBLIC repository '+full+'…')
    run([gh,'repo','create',full,'--public','--description','MyEngine 2 project package','--source',str(root),'--remote','origin'],root)
    try:
        progress('Uploading project files…');run([git,'push','-u','origin','main'],root,timeout=600)
    except Exception as ex:raise RuntimeError('Repository '+full+' was created, but push failed. The local commit remains at '+str(root)+'. '+str(ex)) from ex
    url='https://'+owner+'.github.io/'+name+'/'
    warnings=[]
    try:
        run([gh,'api','--method','PUT','repos/'+full+'/topics','--input','-'],root,input_text=json.dumps({'names':['mypakege','myengine2']}))
        run([gh,'api','--method','PATCH','repos/'+full,'-f','homepage='+url],root)
    except Exception as ex:warnings.append('Files uploaded; topic/homepage update failed: '+str(ex))
    try:
        run([gh,'api','--method','POST','repos/'+full+'/pages','--input','-'],root,input_text=json.dumps({'source':{'branch':'main','path':'/'}}))
    except Exception as ex:warnings.append('Files uploaded; enable Pages in repository Settings → Pages (main, root). '+str(ex))
    return {'repository':'https://github.com/'+full,'pages':url,'warnings':warnings}

def clone_package(full,parent):
    full=valid_repo(full);git=executable('git')
    if not git:raise RuntimeError('Install Git for Windows, then restart the Hub')
    parent=Path(parent).resolve();name=safe_name(full.split('/')[1]);target=parent/name
    if target.exists():raise FileExistsError('Destination already exists. Choose another parent folder.')
    parent.mkdir(parents=True,exist_ok=True);stage=Path(tempfile.mkdtemp(prefix='.package-',dir=parent))
    try:
        # No checkout hooks from the repository, no submodules, no script execution.
        run([git,'-c','core.hooksPath=','clone','--depth','1','--','https://github.com/'+full+'.git',str(stage)],timeout=600)
        for p in stage.rglob('*'):
            if '.git' not in p.relative_to(stage).parts and p.is_symlink():raise ValueError('Symlink packages are not supported')
        meta=read_project(stage)
        from engine_build import validate_project
        validate_project(stage,meta['mainScene'])
        manifest=stage/'package.json'
        if manifest.exists():
            for item in json.loads(manifest.read_text(encoding='utf-8'))['files']:
                p=inside(stage,item['path'])
                if not p.is_file() or p.stat().st_size!=item['bytes'] or hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Package manifest mismatch: '+item['path'])
        from engine_trust import set_allowed
        set_allowed(stage,False)
        stage.rename(target);return target
    except BaseException:shutil.rmtree(stage,ignore_errors=True);raise
