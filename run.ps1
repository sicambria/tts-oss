$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Virtual environment is missing. Run .\setup.ps1 first."
}

Push-Location $Root
try {
    & $Python app.py
}
finally {
    Pop-Location
}
