param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$archivePython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $archivePython)) { throw 'Run Setup.ps1 first.' }
$archiveUrl = 'http://127.0.0.1:8501'
$archivePidFile = Join-Path $PSScriptRoot 'logs\server.pid'
if (Test-Path -LiteralPath $archivePidFile) {
    $archiveOldPid = [int](Get-Content -LiteralPath $archivePidFile)
    $archiveOldProcess = Get-Process -Id $archiveOldPid -ErrorAction SilentlyContinue
    if ($archiveOldProcess -and $archiveOldProcess.Path -eq $archivePython) {
        if (-not $NoBrowser) { Start-Process $archiveUrl }
        exit
    }
}
New-Item -ItemType Directory -Path (Join-Path $PSScriptRoot 'logs') -Force | Out-Null
$archiveProcess = Start-Process -FilePath $archivePython -ArgumentList '-X utf8 -m streamlit run app.py' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput 'logs\server.log' -RedirectStandardError 'logs\server-error.log'
$archiveProcess.Id | Set-Content -LiteralPath $archivePidFile
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    if ($archiveProcess.HasExited) { throw 'Archive failed to start. See logs/server-error.log; port 8501 may be in use.' }
    try {
        $response = Invoke-WebRequest -Uri "$archiveUrl/_stcore/health" -UseBasicParsing -TimeoutSec 1
        if ($response.StatusCode -eq 200) { if (-not $NoBrowser) { Start-Process $archiveUrl }; exit }
    } catch { }
    Start-Sleep -Milliseconds 500
}
throw 'Archive is not ready. See logs/server-error.log.'
