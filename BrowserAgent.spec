# PyInstaller spec for the Windows desktop app.
#
# Portable build:   pyinstaller BrowserAgent.spec
#   Output: dist/BrowserAgent/BrowserAgent.exe  (onedir: exe + folder, keep together)
# Installer build:  build_installer.bat  (needs Inno Setup once)
#   Output: dist-installer/BrowserAgent-Setup-<version>.exe
#
# Notes:
# - Windowed (no console). First run copies .env.example -> .env by itself.
# - The desktop app drives the user's own Chrome over CDP, so no Playwright
#   browser download is needed for normal use. Playwright's *driver* (node)
#   IS bundled below — without it the frozen exe cannot talk to any browser.
#   If launch-mode is ever used, the app installs Chromium into the per-user
#   %LOCALAPPDATA%\BrowserAgent\ms-playwright dir (see app/env_store.py).
# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

playwright_datas, playwright_binaries, playwright_hiddenimports = collect_all("playwright")

block_cipher = None


a = Analysis(
    ['app/main.py'],
    pathex=[],
    binaries=playwright_binaries,
    datas=[
        ('.env.example', '.'),
        ('tests/fixture/quiz.html', 'tests/fixture'),
    ] + playwright_datas,
    hiddenimports=[
        # Function-level imports PyInstaller's static scan can miss.
        'app.main_window',
        'app.worker',
        'app.env_store',
        'app.dialogs',
        'app.theme',
        'app.logo',
        'agent.controller',
        'agent.action_planner',
        'agent.recovery',
        'agent.state_machine',
        'browser.session',
        'browser.observer',
        'browser.executor',
        'browser.selectors',
        'perception.page_classifier',
        'perception.question_extractor',
        'perception.visual_perception',
        'solver.llm_solver',
        'solver.base',
        'solver.schemas',
        'solver.validation',
        'storage.run_store',
        'verification.verifier',
    ] + playwright_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BrowserAgent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # windowed: no terminal window
    icon='assets/app.ico',
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='BrowserAgent',
)
