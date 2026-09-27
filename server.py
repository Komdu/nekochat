#!/usr/bin/env python3
"""Nekochat server — самодостаточный запуск (по умолчанию SQLite, без Docker/Postgres).

    python server.py                                    # ./nekochat.db, 127.0.0.1:8000
    python server.py --db data.db --host 0.0.0.0 --port 9000
    python server.py --name "Мой сервер"                # имя для клиентов
    python server.py --db postgresql+psycopg2://user:pass@host/db  # любой URL

DATABASE_URL в окружении или в .env имеет приоритет над --db.
"""
import argparse
import os
import sys
from pathlib import Path


def _db_in_dotenv() -> bool:
    """Есть ли DATABASE_URL в .env (pydantic-settings читает его сам)."""
    try:
        for line in Path(".env").read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("DATABASE_URL"):
                return True
    except OSError:
        pass
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="nekochat server")
    ap.add_argument("--db", default="nekochat.db",
                    help="файл SQLite или полный URL БД (по умолчанию: nekochat.db)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--name", default=None,
                    help="имя сервера, которое увидят клиенты (иначе из config.yml)")
    args = ap.parse_args()

    if "DATABASE_URL" not in os.environ and not _db_in_dotenv():
        db = args.db
        os.environ["DATABASE_URL"] = db if "://" in db else "sqlite:///" + os.path.abspath(db)
    if args.name:
        os.environ["NEKOCHAT_SERVER_NAME"] = args.name

    import uvicorn

    print(f"[nekochat] db={os.environ.get('DATABASE_URL', '(из .env)')} "
          f"listen=http://{args.host}:{args.port}")
    uvicorn.run("app.main:app", host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
