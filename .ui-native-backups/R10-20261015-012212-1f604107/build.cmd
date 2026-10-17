@echo off
setlocal
cd /d "%~dp0"

rem Use an existing x64 Native Tools Command Prompt when available.
where ml64.exe >nul 2>nul
if not errorlevel 1 if defined LIB if defined INCLUDE goto build

rem Fallback for VS 2022 Community: no vswhere.exe or vcvars64.bat required.
set "EngineVS=%ProgramFiles%\Microsoft Visual Studio\2022\Community"
set "EngineKits=%ProgramFiles(x86)%\Windows Kits\10"
set "EngineToolset="
set "EngineSDK="
for /f "delims=" %%V in ('dir /b /ad /o-n "%EngineVS%\VC\Tools\MSVC" 2^>nul') do if not defined EngineToolset if exist "%EngineVS%\VC\Tools\MSVC\%%V\bin\Hostx64\x64\ml64.exe" set "EngineToolset=%%V"
for /f "delims=" %%V in ('dir /b /ad /o-n "%EngineKits%\Lib\10.*" 2^>nul') do if not defined EngineSDK if exist "%EngineKits%\Lib\%%V\um\x64\opengl32.lib" set "EngineSDK=%%V"
if not defined EngineToolset goto tools_missing
if not defined EngineSDK goto tools_missing
set "PATH=%EngineVS%\VC\Tools\MSVC\%EngineToolset%\bin\Hostx64\x64;%PATH%"
set "INCLUDE=%EngineVS%\VC\Tools\MSVC\%EngineToolset%\include;%EngineKits%\Include\%EngineSDK%\ucrt;%EngineKits%\Include\%EngineSDK%\shared;%EngineKits%\Include\%EngineSDK%\um;%INCLUDE%"
set "LIB=%EngineKits%\Lib\%EngineSDK%\ucrt\x64;%EngineKits%\Lib\%EngineSDK%\um\x64;%EngineVS%\VC\Tools\MSVC\%EngineToolset%\lib\x64;%LIB%"

:build
rem Locate the Windows resource compiler even when vcvars64 was not used.
where rc.exe >nul 2>nul
if not errorlevel 1 goto resources_ready
set "EngineKits=%ProgramFiles(x86)%\Windows Kits\10"
set "EngineRC="
for /f "delims=" %%V in ('dir /b /ad /o-n "%EngineKits%\bin\10.*" 2^>nul') do if not defined EngineRC if exist "%EngineKits%\bin\%%V\x64\rc.exe" set "EngineRC=%EngineKits%\bin\%%V\x64"
if not defined EngineRC goto tools_missing
set "PATH=%EngineRC%;%PATH%"
:resources_ready
if not exist "build" mkdir "build"
cl.exe /nologo /O2 /EHsc /MT /std:c++17 /LD /Fo"build\Slice4D.obj" /Fe"build\Slice4D.dll" "Slice4D.cpp" /link /IMPLIB:"build\Slice4D.lib"
if errorlevel 1 goto failed
copy /y "build\Slice4D.dll" "Slice4D.dll" >nul
if errorlevel 1 goto exe_locked
rc.exe /nologo /fo "build\MyEngine2.res" "MyEngine2.rc"
if errorlevel 1 goto failed
ml64.exe /nologo /c /Fo"build\Engine.obj" "Engine.asm"
if errorlevel 1 goto failed
ml64.exe /nologo /c /Fo"build\Camera.obj" "Camera.asm"
if errorlevel 1 goto failed
ml64.exe /nologo /c /Fo"build\NativeScene.obj" "NativeScene.asm"
if errorlevel 1 goto failed
ml64.exe /nologo /c /Fo"build\PythonHost.obj" "PythonHost.asm"
if errorlevel 1 goto failed
ml64.exe /nologo /c /Fo"build\Physics.obj" "Physics.asm"
if errorlevel 1 goto failed
link.exe /nologo /SUBSYSTEM:WINDOWS /ENTRY:main /MACHINE:X64 /OUT:"build\MyEngine2.new.exe" "build\Engine.obj" "build\Camera.obj" "build\NativeScene.obj" "build\PythonHost.obj" "build\Physics.obj" "build\MyEngine2.res" kernel32.lib user32.lib gdi32.lib opengl32.lib ^
  /EXPORT:EngineGetCamera /EXPORT:EngineGetKeys /EXPORT:EngineGetLight /EXPORT:EngineGetDelta /EXPORT:EngineGetWindow /EXPORT:EngineSubmitScene /EXPORT:EngineCreateMesh /EXPORT:EngineDeleteMesh /EXPORT:EngineCreateTexture /EXPORT:EngineDeleteTexture /EXPORT:EngineGetCameraControl /EXPORT:EngineGetRuntimeFlags ^
  /EXPORT:EnginePortableV1 /EXPORT:EngineGetRenderFlags /EXPORT:PhysicsPrepare /EXPORT:PhysicsIntegrate /EXPORT:PhysicsBoxBox /EXPORT:PhysicsBoxTriangle /EXPORT:PhysicsBoxContacts /EXPORT:PhysicsMeshContacts /EXPORT:PhysicsSolve
if errorlevel 1 goto failed
echo.
copy /y "build\MyEngine2.new.exe" "MyEngine2.exe" >nul
if errorlevel 1 goto exe_locked
echo Built: "%~dp0MyEngine2.exe"
echo Run setup_python.cmd once, then start_editor.cmd (editor) or MyEngine2.exe (game).
pause
exit /b 0

:exe_locked
echo Cannot replace MyEngine2.exe or Slice4D.dll. Save your scene and close Editor and game windows.
echo Running EXE/DLL files are locked by Windows. No process was force-closed.
echo Run build.cmd again after closing the engine.
pause
exit /b 1

:tools_missing
echo Install Visual Studio 2022 Desktop development with C++ and Windows SDK.
echo Then open "x64 Native Tools Command Prompt for VS 2022" and run build.cmd.
:failed
echo.
echo Build failed. See the error above.
pause
exit /b 1
