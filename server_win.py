"""Nekochat Server — автономный сервер для Windows (без Docker/nginx/NATS).

Запускает FastAPI-приложение напрямую через uvicorn:
  * SQLite-база и аватары — в папке данных (по умолчанию %APPDATA%\\NekochatServer)
  * NATS выключен          — клиенты ходят по /ws (релей звонков работает как обычно)
  * uvicorn сам отдаёт     — REST, /ws, статику (/web, /docs, /admin)

Переменные окружения (необязательны):
  NEKOCHAT_DATA_DIR  — папка данных (иначе %APPDATA%\\NekochatServer)
  NKO_HOST           — адрес прослушивания (по умолчанию 127.0.0.1; для ЛВС/внешнего
                       доступа поставьте 0.0.0.0 — вместе с открытым портом)
  NKO_PORT           — порт (по умолчанию 8001)

Локальный клиент: он по умолчанию смотрит на публичный сервер, но в поле «Сервер»
на экране входа можно указать http://127.0.0.1:8001 (или адрес этой машины в ЛВС).
"""
import os
import secrets
import sys
from pathlib import Path


def _data_dir() -> Path:
    env = os.environ.get("NEKOCHAT_DATA_DIR")
    if env:
        p = Path(env)
    elif sys.platform == "win32":
        p = Path(os.environ.get("APPDATA") or Path.home()) / "NekochatServer"
    else:
        p = Path.home() / ".nekochat"
    p.mkdir(parents=True, exist_ok=True)
    return p


def main() -> None:
    # Консоль Windows может быть cp1252/cp866 — логи и кириллица не должны ронять сервер.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    data = _data_dir()

    # SQLite + аватары в папке данных; NATS выключен (клиенты релеятся через /ws).
    os.environ.setdefault("DATABASE_URL", "sqlite:///" + (data / "nekochat.db").as_posix())
    os.environ.setdefault("AVATARS_DIR", str(data / "avatars"))
    os.environ.setdefault("NATS_ENABLED", "false")

    # Стабильный JWT-секрет — сессии переживают перезапуск сервера.
    secret_file = data / "secret.txt"
    if not secret_file.exists():
        secret_file.write_text(secrets.token_hex(32), encoding="utf-8")
    os.environ.setdefault("JWT_SECRET", secret_file.read_text(encoding="utf-8").strip())

    host = os.environ.get("NKO_HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("NKO_PORT", "8001"))
    except ValueError:
        port = 8001

    try:
        import uvicorn
        from app.main import app  # noqa: F401  (импорт настраивает БД/таблицы)
    except Exception as e:  # pragma: no cover
        print(f"[NekochatServer] Ошибка запуска: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"[NekochatServer] папка данных: {data}")
    print(f"[NekochatServer] слушаю {host}:{port}")
    uvicorn.run(
        app,
        host=host,
        port=port,
        proxy_headers=True,      # не мешает прямому доступу (X-Forwarded-* нам не шлют)
        ws_ping_interval=None,   # liveness прикладной: клиенты шлют {"type":"ping"} раз в 10с
        ws_ping_timeout=None,
        ws_max_size=64 * 1024 * 1024,
    )


if __name__ == "__main__":
    main()