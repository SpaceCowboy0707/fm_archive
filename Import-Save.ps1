param([Parameter(Mandatory=$true)][string]$SavePath)
$ErrorActionPreference = 'Stop'
$archiveSource = (Resolve-Path -LiteralPath $SavePath).Path
Set-Location -LiteralPath $PSScriptRoot
& '.\.venv\Scripts\python.exe' -X utf8 -m src.import_save $archiveSource
if ($LASTEXITCODE -ne 0) { throw 'Import failed; check the error above.' }
