param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$workspaceRoot = $PSScriptRoot
$workspacePython = Join-Path $workspaceRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $workspacePython)) { throw 'Run Setup.ps1 first.' }
New-Item -ItemType Directory -Path (Join-Path $workspaceRoot 'logs') -Force | Out-Null
try { $workspaceHealth = Invoke-WebRequest 'http://127.0.0.1:8502/api/config' -UseBasicParsing -TimeoutSec 3 } catch { $workspaceHealth = $null }
if (-not $workspaceHealth) {
    $workspaceProcess = Start-Process -FilePath $workspacePython -ArgumentList '-X utf8 ui-preview/server.py' -WorkingDirectory $workspaceRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $workspaceRoot 'logs\workspace.log') -RedirectStandardError (Join-Path $workspaceRoot 'logs\workspace-error.log')
    $workspaceProcess.Id | Set-Content -LiteralPath (Join-Path $workspaceRoot 'logs\workspace.pid')
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        if ($workspaceProcess.HasExited) { throw 'Workspace startup failed. See logs/workspace-error.log.' }
        try { $workspaceHealth = Invoke-WebRequest 'http://127.0.0.1:8502/api/config' -UseBasicParsing -TimeoutSec 1; break } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $workspaceHealth) { throw 'Workspace did not become ready.' }
}
if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:8502' }
