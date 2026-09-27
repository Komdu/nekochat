"""GET /nats/creds — параметры NATS-подключения для аутентифицированного клиента.

Phase 1: статичные юзер/пароль nats-server (NATS_WS_USER / NATS_WS_PASS), выдаются
по JWT. Per-user ACL / auth_callout — Фаза 2.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..config import settings
from ..deps import get_current_user
from ..models import User

router = APIRouter()


class NatsCreds(BaseModel):
    """Параметры подключения клиента к nats-server (по WSS туннеля, путь /nats)."""

    url: str = Field(description="wss://host/nats — куда коннектиться NATS-клиенту")
    user: str
    password: str
    uid: int
    ping: int = Field(10, description="клиент шлёт {type:ping} раз в N сек (server presence)")
    silence: int = Field(45, description="тишина дольше N сек -> сервер считает юзера offline")


@router.get("/nats/creds", response_model=NatsCreds, summary="NATS-креды (для транспорта nats)")
def nats_creds(request: Request, user: User = Depends(get_current_user)):
    if not settings.nats_enabled:
        raise HTTPException(status_code=503, detail="NATS transport disabled")
    scheme = request.url.scheme
    host = request.url.netloc
    # Всегда wss: клиент ходит через TLS-туннель (nginx/catch-all Cloudflare),
    # схема HTTPS на стороне origin не должна влиять на NATS-URL.
    return NatsCreds(
        url=f"wss://{host}/nats",
        user=settings.nats_ws_user,
        password=settings.nats_ws_pass,
        uid=user.id,
        ping=settings.nats_ping_interval_s,
        silence=settings.nats_silence_s,
    )