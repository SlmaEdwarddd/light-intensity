# -*- mode: python ; coding: utf-8 -*-


block_cipher = None


a = Analysis(
    ['20260506.py'],
    pathex=[],
    binaries=[('C:\\XIMEA\\API\\Python\\v3\\ximea\\libs\\64bit\\XiApi64.dll', '.'),
        ('C:\\XIMEA\\API\\Python\\v3\\ximea\\libs\\64bit\\XiArrOps64.dll', '.')],
    datas=[],
    hiddenimports=[],
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='light_intensity',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
