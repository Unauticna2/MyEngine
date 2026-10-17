"""Local project script permission, plus an independent permission on each object."""
from pathlib import Path
import json
from engine_scene import atomic_json

def allowed(root):
 p=Path(root)/'.myengine/trust.json'
 if not p.exists():return True  # Existing local projects retain their behaviour.
 try:return json.loads(p.read_text(encoding='utf-8')).get('allowScripts') is True
 except (OSError,ValueError):return False

def set_allowed(root,value):atomic_json(Path(root)/'.myengine/trust.json',{'allowScripts':bool(value)})
