@echo off
cd /d "%~dp0"
MyEngine2.exe map-features25.json
if errorlevel 1 pause
