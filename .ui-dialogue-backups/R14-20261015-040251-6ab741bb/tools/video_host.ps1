$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
Add-Type -AssemblyName PresentationFramework,PresentationCore,WindowsBase,System.Web.Extensions
$dll=Join-Path (Split-Path $PSScriptRoot -Parent) 'MyEngineVideo.dll'
[void][Reflection.Assembly]::LoadFrom($dll)
[MyEngineVideoHost]::Run($env:MYENGINE_VIDEO_CONTROL)
