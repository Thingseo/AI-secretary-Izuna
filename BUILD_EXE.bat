@echo off
setlocal
cd /d "%~dp0"
call setup.bat
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip install pyinstaller==6.12.0
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onedir --name IzunaDesktop --add-data "assets;assets" launcher.py
if errorlevel 1 goto failed
echo.
echo Build complete: dist\IzunaDesktop\IzunaDesktop.exe
echo Keep the entire dist\IzunaDesktop folder together.
pause
exit /b 0
:failed
echo Build failed. See the error above.
pause
exit /b 1
