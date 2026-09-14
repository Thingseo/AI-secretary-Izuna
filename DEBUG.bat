@echo off
setlocal
cd /d "%~dp0"
if exist "runtime\python.exe" (
    "runtime\python.exe" "app.py"
) else (
    call setup.bat
    if errorlevel 1 goto done
    ".venv\Scripts\python.exe" "app.py"
)
:done
pause
