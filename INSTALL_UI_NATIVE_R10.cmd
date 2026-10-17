@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
where py.exe >nul 2>nul
if errorlevel 1 goto use_python
py -3 "%~dp0install_ui_native_r10.py" %*
goto finished
:use_python
python "%~dp0install_ui_native_r10.py" %*
:finished
pause
