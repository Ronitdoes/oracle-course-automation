@echo off
REM Portable Windows build (no installer, no admin needed to build).
REM Run from project root. Requires: pip install -r requirements.txt
REM Output: dist\BrowserAgent\BrowserAgent.exe (+ its folder — keep together).
setlocal
python -m PyInstaller --version >NUL 2>&1
if errorlevel 1 (
  echo PyInstaller is missing. Run:  pip install -r requirements.txt
  exit /b 1
)
python -m PyInstaller -y BrowserAgent.spec
if errorlevel 1 exit /b 1
echo.
echo Done. Portable app: dist\BrowserAgent\BrowserAgent.exe
echo For a real installer (Start Menu entry + uninstaller), run build_installer.bat
