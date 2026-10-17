@echo off
setlocal
cd /d "%~dp0"

rem Use an existing x64 Native Tools Command Prompt when available.
where cl.exe >nul 2>nul
if not errorlevel 1 if defined LIB if defined INCLUDE goto build

rem Fallback for VS 2022 Community: no vswhere.exe or vcvars64.bat required.
set "EngineVS=%ProgramFiles%\Microsoft Visual Studio\2022\Community"
set "EngineKits=%ProgramFiles(x86)%\Windows Kits\10"
set "EngineToolset="
set "EngineSDK="
for /f "delims=" %%V in ('dir /b /ad /o-n "%EngineVS%\VC\Tools\MSVC" 2^>nul') do if not defined EngineToolset if exist "%EngineVS%\VC\Tools\MSVC\%%V\bin\Hostx64\x64\cl.exe" set "EngineToolset=%%V"
for /f "delims=" %%V in ('dir /b /ad /o-n "%EngineKits%\Lib\10.*" 2^>nul') do if not defined EngineSDK if exist "%EngineKits%\Lib\%%V\um\x64\opengl32.lib" set "EngineSDK=%%V"
if not defined EngineToolset goto tools_missing
if not defined EngineSDK goto tools_missing
set "PATH=%EngineVS%\VC\Tools\MSVC\%EngineToolset%\bin\Hostx64\x64;%PATH%"
set "INCLUDE=%EngineVS%\VC\Tools\MSVC\%EngineToolset%\include;%EngineKits%\Include\%EngineSDK%\ucrt;%EngineKits%\Include\%EngineSDK%\shared;%EngineKits%\Include\%EngineSDK%\um;%INCLUDE%"
set "LIB=%EngineKits%\Lib\%EngineSDK%\ucrt\x64;%EngineKits%\Lib\%EngineSDK%\um\x64;%EngineVS%\VC\Tools\MSVC\%EngineToolset%\lib\x64;%LIB%"

:build
if not exist "build" mkdir "build"
cl.exe /nologo /O2 /EHsc /MT /std:c++17 /LD /Fo"build\MyEngineUI.obj" /Fe"build\MyEngineUI.dll" "MyEngineUI.cpp" /link /IMPLIB:"build\MyEngineUI.lib"
if errorlevel 1 goto failed
copy /y "build\MyEngineUI.dll" "MyEngineUI.dll" >nul
if errorlevel 1 goto locked
echo Built MyEngineUI.dll. Restart the editor / player to load it.
pause
exit /b 0
:locked
echo DLL is in use. Close Editor and game windows, then run this file again.
goto failed
:tools_missing
echo Install Visual Studio 2022 Desktop development with C++ and Windows SDK.
echo Or use the included prebuilt Windows x64 MyEngineUI.dll.
:failed
echo Build failed. See the error above.
pause
exit /b 1
