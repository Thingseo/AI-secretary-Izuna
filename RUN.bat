@echo off
setlocal
cd /d "%~dp0"
if exist "runtime\pythonw.exe" (
    start "" "runtime\pythonw.exe" "launcher.py"
    exit /b 0
)
call setup.bat
if errorlevel 1 (
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "launcher.py"
