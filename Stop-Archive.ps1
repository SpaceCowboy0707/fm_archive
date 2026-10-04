$ErrorActionPreference = 'Stop'
$archivePidFile = Join-Path $PSScriptRoot 'logs\server.pid'
if (Test-Path -LiteralPath $archivePidFile) {
    $archiveProcess = Get-Process -Id ([int](Get-Content -LiteralPath $archivePidFile)) -ErrorAction SilentlyContinue
    $archivePython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if ($archiveProcess -and $archiveProcess.Path -eq $archivePython) { Stop-Process -Id $archiveProcess.Id }
}
