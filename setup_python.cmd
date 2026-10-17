@echo off
setlocal
cd /d "%~dp0"
py -3.13 setup_python.py
if not errorlevel 1 goto done
py -3.12 setup_python.py
if not errorlevel 1 goto done
py -3.11 setup_python.py
if not errorlevel 1 goto done
python setup_python.py
if not errorlevel 1 goto done
echo Could not configure Python. Install normal 64-bit Python 3.11-3.13.
pause
exit /b 1
:done
pause
exit /b 0
