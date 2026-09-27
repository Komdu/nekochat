#!/usr/bin/env bash
# Сборка десктоп-клиента (один бинарник, без сервера) через PySide6 + PyInstaller.
# Собрать на той ОС, где бинарник будет запускаться (без кросскомпиляции).
set -euo pipefail
cd "$(dirname "$0")/.."

PY=${PY:-python3}
if [ ! -d .venv ]; then
  "$PY" -m venv .venv
fi
./.venv/bin/pip install -q -r requirements-client.txt

./.venv/bin/pyinstaller --noconfirm --onefile --name nekochat-client \
  --add-data "icon.png:." \
  --hidden-import "PySide6.QtWebEngineWidgets" \
  --hidden-import "PySide6.QtWebEngineCore" \
  --collect-all PySide6 \
  client_app.py

echo "Готово: dist/nekochat-client"
ls -lh dist/nekochat-client