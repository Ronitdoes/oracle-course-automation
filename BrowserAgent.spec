# PyInstaller spec for the portable Windows .exe.
# Build:  pyinstaller BrowserAgent.spec
# Output: dist/BrowserAgent/BrowserAgent.exe  (onedir, recommended for Playwright)
#         use --onefile variant only if you bundle the browser separately.
# First run downloads Chromium via `playwright install chromium` from the app.
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['app/main.py'],
    pathex=[],
    binaries=[],
    datas=[('.env.example', '.'), ('tests/fixture/quiz.html', 'tests/fixture')],
    hiddenimports=['playwright', 'pydantic', 'dotenv', 'httpx'],
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
