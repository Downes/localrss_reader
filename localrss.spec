# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

backend_datas, backend_binaries, backend_imports = [], [], []
for package in ("flask", "aiohttp", "feedparser", "clist_server_admin", "clist_kvstore_auth"):
    data, binaries, imports = collect_all(package)
    backend_datas.extend(data)
    backend_binaries.extend(binaries)
    backend_imports.extend(imports)

block_cipher = None

a = Analysis(
    ['tray_app.py'],
    pathex=[],
    binaries=backend_binaries,
    datas=[
        ('app.py', '.'),
        ('static', 'static'),
        ('feeds.opml', '.'),
    ] + backend_datas,
    hiddenimports=[
        'flask',
        'aiohttp',
        'feedparser',
        'pystray',
        'PIL',
        'sqlite3',
    ] + backend_imports,
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
    name='LocalRSS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # No console window
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
    name='LocalRSS',
)
