"""Use the same CPython installation configured for the native engine."""
import configparser
from pathlib import Path
import subprocess
import sys
root=Path(__file__).resolve().parent
ini=root/'python.ini'
interpreter=Path(sys.executable)
if ini.exists():
    config=configparser.ConfigParser()
    config.read(ini,encoding='utf-16')
    candidate=Path(config.get('Python','Home'))/'python.exe'
    if candidate.is_file():interpreter=candidate
args=sys.argv[1:];script='MyEngine2Editor.py'
if args and args[0]=='--hub':script='MyEngineHub.py';args=args[1:]
raise SystemExit(subprocess.call([str(interpreter),str(root/script),*args],cwd=root))
