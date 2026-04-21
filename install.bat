@echo off
setlocal EnableExtensions

set "ROOT=%~dp0"
set "TORCH_CHANNEL=%~1"
if "%TORCH_CHANNEL%"=="" set "TORCH_CHANNEL=cpu"

if /I not "%TORCH_CHANNEL%"=="cpu" if /I not "%TORCH_CHANNEL%"=="cu121" (
    echo Unsupported torch channel "%TORCH_CHANNEL%".
    echo Usage: install.bat [cpu^|cu121]
    exit /b 1
)

call :resolve_python
if errorlevel 1 (
    echo Python 3.11 was not found. Attempting to install it with winget...
    call :install_python
    if errorlevel 1 exit /b 1
    call :resolve_python
    if errorlevel 1 (
        echo Python 3.11 still could not be resolved after installation.
        exit /b 1
    )
)

echo Using Python: %PYTHON_CMD%
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%setup.ps1" -TorchChannel "%TORCH_CHANNEL%"
exit /b %ERRORLEVEL%

:resolve_python
set "PYTHON_CMD="
py -3.11 -c "import sys" >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=py -3.11"
    exit /b 0
)

python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)" >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=python"
    exit /b 0
)

if exist "%LocalAppData%\Programs\Python\Python311\python.exe" (
    set "PYTHON_CMD=%LocalAppData%\Programs\Python\Python311\python.exe"
    exit /b 0
)

if exist "%ProgramFiles%\Python311\python.exe" (
    set "PYTHON_CMD=%ProgramFiles%\Python311\python.exe"
    exit /b 0
)

exit /b 1

:install_python
winget --version >nul 2>nul
if errorlevel 1 (
    echo winget is not available on this machine.
    echo Install Python 3.11 manually from python.org, then rerun install.bat.
    exit /b 1
)

winget install --id Python.Python.3.11 --exact --source winget --accept-package-agreements --accept-source-agreements --silent
if errorlevel 1 (
    echo winget could not install Python 3.11.
    exit /b 1
)

exit /b 0
