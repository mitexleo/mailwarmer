# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.building.api import EXE, PYZ, COLLECT, BUNDLE

block_cipher = None

a = Analysis(
    ['warmup.py', 'warmup_core.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['PySide6.QtNetwork'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='warmup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

app = BUNDLE(
    exe,
    name='MailWarmer.app',
    icon='assets/icon.icns',
    bundle_identifier='dev.mueen.mailwarmer',
    bundle_version='1.5.6',
    bundle_name='Mail Warmer',
)
