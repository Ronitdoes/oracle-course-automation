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
python -m PyInstaller -y BrowserAgent.spec
if errorlevel 1 exit /b 1
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "PATH=%PATH%;C:\Program Files (x86)\Inno Setup 6"
if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set "PATH=%PATH%;C:\Program Files\Inno Setup 6"
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
REM Optional signing: if you own a code-signing certificate, set CERT_THUMBPRINT
REM to its SHA1 thumbprint and both the exe and the installer get signed
REM (signed apps no longer trigger the "unknown publisher" SmartScreen warning).
REM Needs Windows SDK signtool on PATH.
if defined CERT_THUMBPRINT (
  echo Signing with certificate %CERT_THUMBPRINT% ...
  signtool sign /sha1 %CERT_THUMBPRINT% /tr http://timestamp.digicert.com /td sha256 /fd sha256 dist\BrowserAgent\BrowserAgent.exe
  if errorlevel 1 exit /b 1
  for %%F in (dist-installer\BrowserAgent-Setup-*.exe) do signtool sign /sha1 %CERT_THUMBPRINT% /tr http://timestamp.digicert.com /td sha256 /fd sha256 "%%F"
  if errorlevel 1 exit /b 1
  echo Signed.
) else (
  echo Unsigned build (no CERT_THUMBPRINT set) - Windows SmartScreen will warn on first run; see README.
)
