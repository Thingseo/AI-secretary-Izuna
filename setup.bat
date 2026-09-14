@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto deps
py -3.12 -c "import sys" >nul 2>nul
if not errorlevel 1 (
    py -3.12 -m venv .venv
    if errorlevel 1 goto failed
    goto deps
)
python -c "import sys; assert (3,10) <= sys.version_info[:2] < (3,14)" >nul 2>nul
if not errorlevel 1 (
    python -m venv .venv
    if errorlevel 1 goto failed
    goto deps
)
echo.
echo Python 3.12 ^(64-bit^) is required for this launcher.
echo Install it from https://www.python.org/downloads/windows/
echo Enable "Add python.exe to PATH", then run RUN.bat again.
echo.
exit /b 1
:deps
.venv\Scripts\python.exe -c "import PySide6; assert PySide6.__version__ == '6.8.3'" >nul 2>nul
if not errorlevel 1 exit /b 0
echo Installing Izuna Desktop dependencies. First launch may take a few minutes...
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
exit /b 0
:failed
echo Setup failed. Check your Internet connection and Python installation.
exit /b 1
