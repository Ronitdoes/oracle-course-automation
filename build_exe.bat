@echo off
REM Build the portable Windows app (run from project root).
REM Requires: pip install -r requirements.txt  +  playwright install chromium (for local runs)
pyinstaller BrowserAgent.spec
echo Done. See dist\BrowserAgent\BrowserAgent.exe
