param(
    [ValidateSet("cpu", "cu121")]
    [string]$TorchChannel = "cpu"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = "C:\Python311\python.exe"

if (-not (Test-Path $Python)) {
    throw "Python 3.11 was not found at $Python. Install Python 3.11 and rerun this script."
}

Push-Location $Root
try {
    if (-not (Test-Path ".venv")) {
        & $Python -m venv .venv
    }

    $VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
    $PiperVoiceDir = Join-Path $Root "voices\piper"

    & $VenvPython -m pip install --upgrade pip setuptools wheel

    if ($TorchChannel -eq "cpu") {
        & $VenvPython -m pip install torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cpu
    }
    else {
        & $VenvPython -m pip install torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu121
    }

    & $VenvPython -m pip install -r requirements.txt
    New-Item -ItemType Directory -Force -Path $PiperVoiceDir | Out-Null
    & $VenvPython -m piper.download_voices hu_HU-anna-medium en_US-lessac-medium en_GB-alan-medium --download-dir $PiperVoiceDir

    Write-Host ""
    Write-Host "Setup complete."
    Write-Host "Installed Piper voices: hu_HU-anna-medium, en_US-lessac-medium, en_GB-alan-medium"
    Write-Host "Run the app with: .\run.ps1"
}
finally {
    Pop-Location
}
