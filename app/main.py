import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .config import settings
from .database import Base, engine, get_db
from .deps import get_current_user
from .docs_page import docs_page_html
from .models import User
from . import admin
from .nats_bridge import nats_bridge
from .routers import auth, avatars, http_stream, nats_creds, rooms, users, ws, ws_media

APP_VERSION = "0.10.0"  # версия сервера: /api/server-info, лендинг, /download-страница

Base.metadata.create_all(bind=engine)

# ---- tiny migrations for schema added after first deploy ----
def _ensure_column(table: str, column: str, ddl: str):
    try:
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
    except Exception:
        pass  # column already exists


_ensure_column("users", "avatar", "avatar VARCHAR(255)")
_ensure_column("users", "is_banned", "is_banned BOOLEAN DEFAULT FALSE")

_avatar_dir = Path(settings.avatars_dir)
_avatar_dir.mkdir(parents=True, exist_ok=True)


class NoCacheHTML(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path in ("/", "/index.html", "/web/", "/web/index.html"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return response


class ClientHeader(BaseHTTPMiddleware):
    """Разбирает заголовок клиента и кладёт результат в request.state.

    Строгий режим (client_header_strict) выключен по умолчанию намеренно:
    заголовок приходит от того, кого мы опознаём, поэтому подделать его так же
    просто, как послать. Зато отказ ломает всё, что не наш клиент: curl,
    скрипты, health-чеки, сторонние интеграции. Польза при нулевой защите не
    окупает такую цену. Включается одним флагом.
    """

    async def dispatch(self, request: Request, call_next):
        from .client_header import HEADER, WS_PARAM, parse, stats

        raw = request.headers.get(HEADER) or request.headers.get(HEADER.lower())
        if not raw:
            # из браузера WebSocket не умеет заголовки — там тот же хвост
            # едет параметром в URL (net.ts добавляет c=...)
            raw = request.query_params.get(WS_PARAM)
        info = parse(raw)
        stats.note(info)
        request.state.client = info
        if not info.name and settings.client_header_strict:
            stats.rejected += 1
            return JSONResponse(
                {"error": "client_header not found! please update",
                 "detail": f"добавь заголовок {settings.client_header_name}: "
                           "имя/версия (ос) build=метка"},
                status_code=400,
            )
        return await call_next(request)


# /api/docs — Swagger UI для REST-API, спек — /api/openapi.json.
# /docs — общая документация проекта (рендер из docs/).


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Запоминаем главный loop: из синхронных эндпоинтов (а /users/me/profile
    # именно такой) рассылки идут через run_coroutine_threadsafe — в пуле
    # потоков своего loop нет.
    import asyncio as _asyncio

    from .ws_manager import set_loop

    set_loop(_asyncio.get_running_loop())
    await nats_bridge.start()
    yield
    await nats_bridge.stop()


app = FastAPI(title="Nekochat", docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json", lifespan=lifespan)

# Звонки идут не REST'ом, а WebSocket-сообщениями; добавляем их в OpenAPI вручную,
# чтобы они были видны в Swagger (схемы + описание + канал /ws).
_CALL_SCHEMAS = {
    "CallSignal": {
        "type": "object",
        "required": ["type", "call_id"],
        "properties": {
            "type": {
                "type": "string",
                "enum": ["call", "call_answer", "call_hangup"],
                "description": "call — приглашение, call_answer — согласие, call_hangup — завершение/отбой",
            },
            "to_id": {"type": "integer", "description": "адресат (для 1-1)", "nullable": True},
            "room_id": {"type": "integer", "description": "комната (вместо to_id)", "nullable": True},
            "call_id": {"type": "string", "description": "идентификатор звонка"},
            "reason": {
                "type": "string",
                "enum": ["declined", "busy", "mic", "no-answer"],
                "description": "причина завершения (опционально)",
                "nullable": True,
            },
        },
        "description": "Сигналинг звонка: сервер — только реле, пересылает сообщение адресату "
                       "(и эхо отправителю). Без WebRTC.",
    },
    "CallAudio": {
        "type": "object",
        "required": ["type", "to_id", "call_id", "seq", "audio"],
        "properties": {
            "type": {"type": "string", "enum": ["call_audio"]},
            "to_id": {"type": "integer"},
            "call_id": {"type": "string"},
            "seq": {"type": "integer", "description": "порядковый номер кадра"},
            "audio": {"type": "string", "format": "byte", "description": "Opus-кадр 20 мс (base64, 48 кГц моно)"},
        },
        "description": "Аудио звонка: Opus-кадр по WebSocket. Сервер пересылает адресату без эха.",
    },
    "ScreenFrame": {
        "type": "object",
        "required": ["type", "to_id", "call_id", "seq", "data"],
        "properties": {
            "type": {"type": "string", "enum": ["screen_frame"]},
            "to_id": {"type": "integer"},
            "call_id": {"type": "string"},
            "seq": {"type": "integer", "description": "порядковый номер кадра"},
            "key": {"type": "boolean", "description": "ключевой кадр (обязательный для старта декодера)"},
            "data": {"type": "string", "format": "byte", "description": "видео-кадр (VP8/VP9), base64"},
        },
        "description": (
            "Демонстрация экрана: видео-кадр по WebSocket (как call_audio). "
            "Сервер пересылает адресату без эха. До этого идут screen_start/screen_stop "
            "(сигналинг, как call/call_hangup)."
        ),
    },
}


_orig_openapi = app.openapi


def _custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    schema = _orig_openapi()
    schema.setdefault("components", {}).setdefault("schemas", {}).update(_CALL_SCHEMAS)
    desc = schema.get("info", {}).get("description") or ""
    desc += (
        "\n\n---\n\n"
        "### Звонки и демонстрация экрана (WebSocket)\n\n"
        "Звонки не являются REST-операциями — это сообщения по каналу `/ws`:\n\n"
        "- `call` — вызвать (`to_id`/`room_id`, `call_id`);\n"
        "- `call_answer` — принять;\n"
        "- `call_hangup` — завершить/отбой (reason: declined/busy/mic/no-answer);\n"
        "- `call_audio` — Opus-кадр 20 мс (base64), сервер релеит адресату;\n"
        "- `screen_start` / `screen_stop` — включить/выключить демонстрацию экрана (`codec`, `width`, `height`);\n"
        "- `screen_frame` — видео-кадр (VP8/VP9, base64), сервер релеит адресату.\n\n"
        "Голосовой канал комнаты: `call` с `room_id` (без `to_id`) — анонс входа в канал, "
        "сервер релеит всем участникам комнаты (рина нет — ненавязчивый инвайт); "
        "`call_answer` с `room_id` — принять; `call_audio` с `room_id` — Opus-кадр, "
        "релей всем, кроме отправителя (клиент микширует N−1); "
        "`call_hangup` с `room_id` и `reason:\"leave\"` — выход из канала. "
        "Экран в канале — `screen_start`/`screen_frame`/`screen_stop` с `room_id`. "
        "Подробно — в `/docs` (раздел «Голосовой канал комнаты»).\n\n"
        "См. схемы `CallSignal`, `CallAudio` и `ScreenFrame`. Пример, как это укладывается в интерфейс, "
        "есть в **UI-клиентах** (`/web/`, нативный `desktop/`).\n\n"
        "---\n\n"
        "### NATS-транспорт (Phase 1)\n\n"
        "Реальное время можно вести не по `/ws`, а через **nats-server** за тем же туннелем (WSS).\n\n"
        "- Креды: `GET /nats/creds` (по JWT) → `{url, user, password, uid}`;\n"
        "- Подключение: NATS-клиент (`nats.ws`, `nats.java`, `nats-py`) на `wss://…/nats` "
        "(путь туннеля `/nats` → nats-server :8081);\n"
        "- Субъекты:\n"
        "  - `nkc.in.<uid>` — клиент → сервер (те же JSON-сообщения, что по `/ws`);\n"
        "  - `nkc.out.<uid>` — сервер → клиент (события юзера: `status`, сообщения, звонки, `pong`);\n"
        "- Автореконнект встроен в NATS-клиенты; nats-server шлёт PING каждые 10 с — "
        "полусдохшие соединения выкидываются на уровне протокола;\n"
        "- Presence: «online» с первого входящего сообщения, «offline» после 45 с тишины "
        "(half-open guard на стороне сервера).\n\n"
        "Переключение UI: `localStorage.setItem('nc_transport','nats')` или Настройки → «NATS (WSS)»."
    )
    schema.setdefault("info", {})["description"] = desc

    # канал /ws виден в Swagger как «WebSocket»
    schema.setdefault("paths", {})["/ws"] = {
        "get": {
            "summary": "WebSocket-канал (сообщения, статусы, звонки)",
            "description": (
                "Подключение: `/ws?token=<JWT>`. Авторизация — как у REST.\n\n"
                "Клиент → сервер: `room_message`, `direct_message`, `call*`, `call_audio`, `screen_frame`, `ping`.\n"
                "Сервер → клиент: `status`, `room_message`, `direct_message`, `call*`, `error`.\n\n"
                "Звонки и демонстрация экрана — см. `CallSignal`/`CallAudio`/`ScreenFrame`."
            ),
            "parameters": [
                {
                    "name": "token",
                    "in": "query",
                    "required": True,
                    "schema": {"type": "string"},
                    "description": "JWT из /auth/login или /auth/register",
                }
            ],
            "responses": {
                "101": {"description": "WebSocket upgrade"},
                "401": {"description": "Токен невалиден (close 4401)"},
            },
            "x-websocket": True,
        }
    }
    # канал /nats — «внешний» вход NATS (nats-server за туннелем); документация для кастомных клиентов
    schema.setdefault("paths", {})["/nats"] = {
        "get": {
            "summary": "NATS-канал (WSS; как /ws, но через nats-server)",
            "description": (
                "Не HTTP-route приложения: путь `/nats` туннеля Cloudflare смотрит на "
                "nats-server (:8081, websocket). Подключение кастомного клиента:\n\n"
                "1. `GET /nats/creds` (JWT) → url / user / password / uid;\n"
                "2. NATS-клиент: `SUB nkc.out.<uid>`, затем `PUB nkc.in.<uid>`;\n"
                "3. Формат сообщений — как у `/ws` (`CallSignal`, `CallAudio`, `ScreenFrame`, `ping`/`pong`)."
            ),
            "responses": {
                "101": {"description": "NATS websocket upgrade (nats-server за туннелем)"},
                "401": {"description": "Неверные NATS-креды (CONNECT не принят)"},
            },
            "x-websocket": True,
        }
    }
    app.openapi_schema = schema
    return schema


app.openapi = _custom_openapi

app.add_middleware(NoCacheHTML)
# Заголовок клиента: разбор идёт всегда, отказ — только при client_header_strict
# (по умолчанию выключено, см. ClientHeader)
app.add_middleware(ClientHeader)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(rooms.router)
app.include_router(users.router)
app.include_router(avatars.router)
app.include_router(ws.router)
app.include_router(ws_media.router)
app.include_router(http_stream.router)
app.include_router(nats_creds.router)
app.include_router(admin.router)


@app.get("/api/me", response_model=dict)
def me(request: Request, user: User = Depends(get_current_user)):
    from .client_header import parse

    info = parse(request.headers.get(settings.client_header_name) or request.query_params.get("c"))
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "avatar": user.avatar,
        "bio": user.bio,
        "profile_color": user.profile_color,
        "status": user.status,
        "banner": user.banner,
        "is_online": user.is_online,
        # чем сидит и какая версия: /api/me возвращает это самому клиенту,
        # /users — про всех остальных
        "client": info.as_dict(),
        "min_version": settings.client_min_version,
    }


@app.get("/api/client-stats", response_model=dict)
def client_stats():
    """Кто и чем заходит. Открытый эндпоинт: там нет ничего, что не видно
    из самого заголовка, — просто счётчики, чтобы смотреть глазами, а не по
    логам."""
    from .client_header import stats

    return stats.as_dict()


def _static_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "app" / "static"
    return Path(__file__).resolve().parent.parent / "app" / "static"


def _read_config() -> dict:
    """config.yml рядом с сервером (имя, описание, параметры скачивания)."""
    import yaml

    try:
        raw = Path("config.yml").read_text(encoding="utf-8")
        cfg = yaml.safe_load(raw) or {}
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def _download_path(cfg: dict) -> Optional[Path]:
    p = cfg.get("download_path") or os.environ.get("NEKOCHAT_DOWNLOAD_PATH")
    if not p:
        return None
    path = Path(p)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def _fmt_size(n: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "Б" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} ТБ"


@app.get("/docs", response_class=HTMLResponse)
def docs_page():
    """Общая документация проекта (docs/) — отдельно от REST OpenAPI (/api/docs)."""
    return HTMLResponse(docs_page_html())


@app.get("/openapi.json")
def openapi_alias():
    """Алиас машинного спека по старым ссылкам (полный спек — /api/openapi.json)."""
    return JSONResponse(app.openapi())


@app.get("/api/server-info")
def server_info():
    """Метаданные сервера: адресник при проверке статуса, лендинг для кнопки скачивания."""
    cfg = _read_config()
    dl_path = _download_path(cfg)
    size = _fmt_size(dl_path.stat().st_size) if dl_path and dl_path.is_file() else None
    return {
        "name": os.environ.get("NEKOCHAT_SERVER_NAME") or cfg.get("name") or "nekochat",
        "description": cfg.get("description") or "",
        "version": cfg.get("version") or APP_VERSION,
        "sqlite": str(engine.url).startswith("sqlite"),
        "download_url": cfg.get("download_url") or None,
        "download_size": size,
    }


@app.get("/api/health")
def health():
    """Публичный пульс сервера — для кастомных клиентов и мониторинга."""
    return {"ok": True, "version": _read_config().get("version") or APP_VERSION}


@app.get("/download")
def download():
    """Раздача собранного клиента (dist/Nekochat.exe на сервере или download_url в config.yml)."""
    cfg = _read_config()
    path = _download_path(cfg)
    if not path or not path.is_file():
        return JSONResponse(
            {"error": "Файл сборки не загружен на сервер",
             "detail": "download_not_configured"},
            status_code=404,
        )
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename="Nekochat.exe",
        headers={
            "Content-Disposition": 'attachment; filename="Nekochat.exe"',
            "Cache-Control": "public, max-age=3600",
        },
    )


app.mount("/", StaticFiles(directory=str(_static_dir()), html=True), name="static")