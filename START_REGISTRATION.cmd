@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
where py >nul 2>nul
if errorlevel 1 (
    python register_certificate.py
) else (
    py -3 register_certificate.py
)
if errorlevel 1 pause
