# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for MoonScan.

Builds a one-folder distribution. We deliberately use --onedir rather than
--onefile because:
  1. Single-exe builds with PyInstaller frequently trip Windows Defender
     and other antivirus heuristics, which would hurt alliance distribution.
  2. The 30 MB eve_static.db sits next to the exe and is easier to update
     in place than re-extracting a one-file bundle each launch.
  3. Startup is faster (no temp extraction).

Build with:
    pyinstaller moonscan.spec
The output ends up in dist/MoonScan/. Zip that folder for distribution.
"""

from pathlib import Path

block_cipher = None

PROJECT = Path('.').resolve()

a = Analysis(
    ['moonscan/__main__.py'],
    pathex=[str(PROJECT)],
    binaries=[],
    datas=[
        # (source, target_dir_in_bundle)
        (str(PROJECT / 'data' / 'eve_static.db'), 'data'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Trim unused Qt modules. Comment any back in if you hit ImportError.
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

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MoonScan',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,           # UPX often triggers AV heuristics; not worth it
    console=False,       # GUI app — no console window on Windows
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='icon.ico',   # add an .ico file at the project root to set the icon
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='MoonScan',
)
