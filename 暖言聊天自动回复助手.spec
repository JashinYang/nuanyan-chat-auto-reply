# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hiddenimports = []
hiddenimports += collect_submodules('uiautomation')
hiddenimports += collect_submodules('webview')
hiddenimports += collect_submodules('windows_capture')
datas = [
    ('app.ico', '.'),
    ('README.md', '.'),
    ('LICENSE', '.'),
    ('PRIVACY.md', '.'),
    ('THIRD_PARTY_NOTICES.txt', '.'),
    ('THIRD_PARTY_COMPONENTS.md', '.'),
    ('THIRD_PARTY_LICENSES', 'THIRD_PARTY_LICENSES'),
]
datas += collect_data_files('uiautomation')


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PIL'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='暖言聊天自动回复助手',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['app.ico'],
    contents_directory='lib',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='暖言聊天自动回复助手',
)
