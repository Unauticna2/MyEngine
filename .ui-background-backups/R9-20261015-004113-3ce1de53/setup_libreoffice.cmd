@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto usepython
py -3 setup_libreoffice.py
goto finished
:usepython
python setup_libreoffice.py
:finished
if errorlevel 1 echo Installation failed. See the message above.
pause
