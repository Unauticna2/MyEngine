param([string]$Sdk = $env:ANDROID_HOME, [string]$Jdk = $env:JAVA_HOME)
$ErrorActionPreference = 'Stop'
if (-not $Sdk) { $Sdk = Join-Path $env:LOCALAPPDATA 'Android\Sdk' }
if (-not (Test-Path (Join-Path $Sdk 'platforms\android-35\android.jar'))) { throw 'Install Android SDK Platform 35 in Android Studio first.' }
if (-not $Jdk) {
    $candidate = Join-Path $env:ProgramFiles 'Android\Android Studio\jbr'
    if (Test-Path (Join-Path $candidate 'bin\javac.exe')) { $Jdk = $candidate }
}
if (-not $Jdk -or -not (Test-Path (Join-Path $Jdk 'bin\javac.exe'))) { throw 'Pass -Jdk with the path to JDK 17 or 21.' }
$env:JAVA_HOME = $Jdk
$env:ANDROID_HOME = $Sdk
$cache = Join-Path $env:LOCALAPPDATA 'MyEngineBuild'
$gradle = Join-Path $cache 'gradle-8.9\bin\gradle.bat'
if (-not (Test-Path $gradle)) {
    New-Item -ItemType Directory -Force -Path $cache | Out-Null
    $zip = Join-Path $cache 'gradle-8.9-bin.zip'
    $sum = (Invoke-WebRequest -UseBasicParsing 'https://services.gradle.org/distributions/gradle-8.9-bin.zip.sha256').Content.Trim().Split(' ')[0]
    Invoke-WebRequest -UseBasicParsing 'https://services.gradle.org/distributions/gradle-8.9-bin.zip' -OutFile $zip
    if ((Get-FileHash $zip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $sum.ToLowerInvariant()) { throw 'Gradle checksum mismatch.' }
    Expand-Archive -Path $zip -DestinationPath $cache -Force
}
& $gradle -p $PSScriptRoot --no-daemon ':app:assembleDebug'
if ($LASTEXITCODE -ne 0) { throw 'APK build failed. Read the error above.' }
Write-Host ('APK: ' + (Join-Path $PSScriptRoot 'app\build\outputs\apk\debug\app-debug.apk'))
