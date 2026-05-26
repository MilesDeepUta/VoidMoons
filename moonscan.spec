# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — builds a single MoonScan.exe with everything bundled
inside (Python runtime, PySide6, the EVE static database, all of it).

The .exe extracts itself to a temp folder on launch (so first start takes
a few seconds), then runs. User data still goes to %APPDATA%\\MoonScan so
nothing is lost when the temp dir is cleaned up.

Build via build.bat (double-click) or:
    pyinstaller moonscan.spec
"""
from pathlib import Path

block_cipher = None
PROJECT = Path('.').resolve()

a = Analysis(
    ['moonscan/__main__.py'],
    pathex=[str(PROJECT)],
    binaries=[],
    datas=[
        (str(PROJECT / 'data' / 'eve_static.db'), 'data'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Trim unused Qt modules to keep the bundle smaller
        'PySide6.QtBluetooth',
        'PySide6.QtMultimedia',
        'PySide6.QtMultimediaWidgets',
        'PySide6.QtNetwork',
        'PySide6.QtNfc',
        'PySide6.QtPositioning',
        'PySide6.QtPrintSupport',
        'PySide6.QtQml',
        'PySide6.QtQuick',
        'PySide6.QtQuick3D',
        'PySide6.QtQuickWidgets',
        'PySide6.QtRemoteObjects',
        'PySide6.QtSensors',
        'PySide6.QtSerialPort',
        'PySide6.QtSql',
        'PySide6.QtTest',
        'PySide6.QtWebChannel',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineQuick',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebSockets',
        'PySide6.QtXml',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Single-file build: everything packed into one .exe
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='MoonScan',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,           # UPX triggers more AV flags than it saves in size
    runtime_tmpdir=None, # extract to OS default temp folder
    console=False,       # GUI app — no console window on Windows
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='icon.ico',   # drop an .ico in the project root if you want one
)
