"""Build identity is metadata, not a file integrity / anti-tamper check."""
from datetime import datetime, timezone
from pathlib import Path
import json
import uuid

ENGINE_VERSION = '2.5'
ENGINE_REVISION = 'R27'
ENGINE_BUILD = '2.5-R27-20261017.4'

def new_build_id():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]

def read_info(root):
    path = Path(root) / 'build.json'
    if path.is_file():
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(value, dict):raise ValueError('build.json must be an object')
        return value
    return {'name':'MyEngine 2', 'version':ENGINE_VERSION, 'engineVersion':ENGINE_VERSION,
            'engineBuild':ENGINE_BUILD, 'buildId':ENGINE_BUILD, 'target':'Windows x64'}

def description(root):
    info = read_info(root)
    lines = [str(info.get('name', 'MyEngine 2')),
             'Версия: ' + str(info.get('version', info.get('engineVersion', 'не указана'))),
             'Сборка: ' + str(info.get('buildId', 'старая сборка без номера')),
             'Движок: ' + str(info.get('engineBuild', info.get('engineVersion', 'не указан')))]
    for key, label in [('createdUtc','Дата UTC'),('target','Платформа')]:
        if info.get(key):lines.append(label + ': ' + str(info[key]))
    release = info.get('release', {})
    if release.get('repository'):lines.extend(['GitHub: '+release['repository'], 'Тег: '+release['tag']])
    return '\n'.join(lines)
