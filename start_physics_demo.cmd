@echo off
cd /d "%~dp0"
if not exist "MyEngine2.exe" goto missing
MyEngine2.exe map-physics.json
exit /b
:missing
echo Run build.cmd first.
pause
