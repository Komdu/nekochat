# -*- mode: python ; coding: utf-8 -*-
"""Сборка NekochatServer.exe (onefile) из server_win.py + app/ (FastAPI-приложение).

Запуск (из корня репозитория):
    python -m PyInstaller server_win.spec --noconfirm --clean
"""

from PyInstaller.building.datastruct import Tree
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = [
    # uvicorn: подтягиваем петлю/протоколы явно (PyInstaller сам их не видит)
    'uvicorn',
    'uvicorn.loops.auto',
    'uvicorn.loops.asyncio',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.protocols.websockets.websockets_impl',
    'uvicorn.lifespan.on',
]
hiddenimports += collect_submodules('websockets')     # WS-протокол uvicorn
hiddenimports += collect_submodules('multipart')      # загрузка аватаров (fastapi)
hiddenimports += collect_submodules('passlib')        # CryptContext('bcrypt') — ленивый импорт хэшера
hiddenimports.append('yaml')                          # import yaml внутри _read_config() в main.py

a = Analysis(
    ['server_win.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'idlelib', 'test', 'unittest', 'pydoc', 'doctest', 'pdb'],
    noarchive=False,
)

# Статика веб-клиента (+ админка) в app/static, документация в docs/ — кладём в
# _MEIPASS/app и _MEIPASS/docs (main.py/docs_page.py читают именно оттуда в frozen).
a.datas += Tree('app', prefix='app', excludes=['__pycache__', 'avatars'])
a.datas += Tree('docs', prefix='docs')

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='NekochatServer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # окно консоли с логами сервера (закрытие окна = остановка)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='desktop\\src-tauri\\icons\\icon.ico',
)