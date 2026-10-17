"""Run once with the installed 64-bit CPython interpreter. No packages downloaded."""
from pathlib import Path
import ctypes
import os
import struct
import sys
import sysconfig

if os.name!='nt':raise SystemExit('Run this setup on Windows.')
if struct.calcsize('P')!=8:raise SystemExit('Install/use 64-bit Python, not 32-bit.')
if sys.implementation.name!='cpython' or not (3,11)<=sys.version_info[:2]<=(3,13):
    raise SystemExit('Use normal CPython 3.11, 3.12 or 3.13 (64-bit).')
if sysconfig.get_config_var('Py_GIL_DISABLED'):
    raise SystemExit('Use the standard CPython build, not the experimental free-threaded build.')
base=Path(sys.base_prefix).resolve()
dll=base/f'python{sys.version_info.major}{sys.version_info.minor}.dll'
if not dll.is_file():raise SystemExit(f'Python DLL not found: {dll}')
if not (base/'Lib'/'encodings').is_dir():raise SystemExit('Use a complete Python installation including the standard library.')
# Validate the actual APIs required by PythonHost.asm before writing configuration.
lib=ctypes.PyDLL(str(dll))
for name in ('Py_SetPythonHome','Py_InitializeEx','PyRun_SimpleString','PyEval_SaveThread','PyEval_RestoreThread','Py_FinalizeEx'):
    getattr(lib,name)
p=Path(__file__).resolve().parent/'python.ini'
p.write_text(f'[Python]\nHome={base}\nDLL={dll}\n',encoding='utf-16')
print(f'Configured CPython {sys.version_info.major}.{sys.version_info.minor}: {base}')
print('Now run build.cmd and MyEngine2.exe.')

try:
    import tkinter
except ImportError:
    print('Editor needs Tcl/Tk: enable tcl/tk and IDLE in the Python installer.')
