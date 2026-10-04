$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:UV_PYTHON_INSTALL_DIR = Join-Path $PSScriptRoot '.tools\python'
$env:UV_CACHE_DIR = Join-Path $PSScriptRoot '.tools\cache'
$archiveUv = Join-Path $PSScriptRoot '.tools\bin\uv.exe'
if (-not (Test-Path -LiteralPath $archiveUv)) {
    $installedUv = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $installedUv) { throw 'Install uv from https://docs.astral.sh/uv/getting-started/installation/ and run Setup.ps1 again.' }
    $archiveUv = $installedUv.Source
}
& $archiveUv python install 3.12 --no-bin
if ($LASTEXITCODE -ne 0) { throw 'Python installation failed.' }
& $archiveUv sync --locked
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
