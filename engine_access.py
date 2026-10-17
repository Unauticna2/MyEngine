"""A local, explicit gameplay choice. No bank, certificate or admin claims are changed."""
from pathlib import Path
import json
import threading
import time

FILE_NAME = 'donation_access.json'
_cache = {}
_lock = threading.Lock()

def unlock_all(root):
    path = Path(root).resolve() / FILE_NAME
    now = time.monotonic()
    with _lock:
        previous = _cache.get(path)
        if previous and now - previous[0] < 1.0:
            return previous[1]
        try:
            value = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
            if not isinstance(value, dict) or type(value.get('unlockAll', False)) is not bool:
                raise ValueError('unlockAll must be true or false')
            enabled = value.get('unlockAll', False)
            error = ''
        except (OSError, ValueError) as ex:
            enabled, error = False, str(ex)
            if not previous or previous[2] != error:
                print('DONATION ACCESS: ' + str(path) + ': ' + error)
        _cache[path] = (now, enabled, error)
        return enabled

def set_unlock_all(root, enabled):
    if type(enabled) is not bool:
        raise TypeError('unlockAll must be a boolean')
    from engine_scene import atomic_json
    path = Path(root).resolve() / FILE_NAME
    atomic_json(path, {'unlockAll': enabled})
    with _lock:
        _cache.pop(path, None)
