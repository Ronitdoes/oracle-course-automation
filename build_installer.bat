@echo off
REM Full pipeline: portable exe -> Windows installer.
REM Run from project root.
REM Requires once: pip install -r requirements.txt  +  Inno Setup (https://jrsoftware.org/isinfo.php)
REM Output: dist-installer\BrowserAgent-Setup-*.exe  (double-click to install)
setlocal
python -m PyInstaller --version >NUL 2>&1
if errorlevel 1 (
  echo PyInstaller is missing. Run:  pip install -r requirements.txt
  exit /b 1
)
python -m PyInstaller BrowserAgent.spec
if errorlevel 1 exit /b 1
where ISCC >NUL 2>&1
if errorlevel 1 (
  echo.
  echo Portable build done: dist\BrowserAgent\BrowserAgent.exe
  echo Inno Setup not found - install it from https://jrsoftware.org/isinfo.php,
  echo then run:  ISCC installer.iss
  exit /b 0
)
ISCC installer.iss
if errorlevel 1 exit /b 1
echo.
echo Done. Installer: dist-installer\BrowserAgent-Setup-*.exe
