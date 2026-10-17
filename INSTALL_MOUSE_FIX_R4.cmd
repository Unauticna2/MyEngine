@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
where py.exe >nul 2>nul
if errorlevel 1 goto use_python
py -3 "%~dp0install_mouse_fix_r4.py" %*
goto finished
:use_python
python "%~dp0install_mouse_fix_r4.py" %*
:finished
pause
