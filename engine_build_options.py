"""Source/library exclusion rules apply to project content, never the private Python runtime."""
from pathlib import Path,PurePosixPath
import json,fnmatch
from engine_scene import atomic_json
DEFAULT_EXTENSIONS=('.c','.cs','.cpp','.asm')

def normalized(extensions=None,files=None):
 ext=list(DEFAULT_EXTENSIONS if extensions is None else extensions);paths=list(files or [])
 ext=[x.strip().lower() for x in ext if x.strip()]
 if any(not x.startswith('.') or '/' in x or '\\' in x or '*' in x for x in ext):raise ValueError('Use extensions such as .c, .cs, .cpp, .asm, .dll')
 for p in paths:
  q=p.replace('\\','/')
  if q.startswith('/') or ':' in q or '..' in PurePosixPath(q).parts:raise ValueError('Exclusion paths must stay inside the project')
 return {'excludeExtensions':sorted(set(ext)),'excludeFiles':[p.replace('\\','/') for p in paths if p.strip()]}

def excluded(relative,options):
 p=str(relative).replace('\\','/');return Path(p).suffix.lower() in options['excludeExtensions'] or any(fnmatch.fnmatchcase(p.lower(),pat.lower()) for pat in options['excludeFiles'])
def load(root):
 try:d=json.loads((Path(root)/'build-options.json').read_text(encoding='utf-8'));return normalized(d.get('excludeExtensions'),d.get('excludeFiles'))
 except FileNotFoundError:return normalized()
def save(root,options):atomic_json(Path(root)/'build-options.json',normalized(options['excludeExtensions'],options['excludeFiles']))
