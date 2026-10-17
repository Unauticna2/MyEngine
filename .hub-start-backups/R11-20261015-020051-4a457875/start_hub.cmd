@echo off
setlocal
cd /d "%~dp0"
where py.exe >nul 2>nul
if errorlevel 1 goto python_command
py -3 launch_editor.py --hub %*
goto finished
:python_command
python launch_editor.py --hub %*
:finished
if errorlevel 1 pause
