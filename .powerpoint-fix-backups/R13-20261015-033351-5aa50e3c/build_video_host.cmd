@echo off
setlocal
cd /d "%~dp0"
set "MYENGINE_CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
set "MYENGINE_WPF=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\WPF"
if not exist "%MYENGINE_CSC%" (
 echo .NET Framework C# compiler not found.
 exit /b 1
)
"%MYENGINE_CSC%" /nologo /target:library /optimize+ /out:MyEngineVideo.dll /r:"%MYENGINE_WPF%\PresentationFramework.dll" /r:"%MYENGINE_WPF%\PresentationCore.dll" /r:"%MYENGINE_WPF%\WindowsBase.dll" /r:System.Xaml.dll /r:System.Web.Extensions.dll tools\video_host.cs
if errorlevel 1 exit /b 1
echo MyEngineVideo.dll built.
