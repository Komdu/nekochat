import asyncio
import json
import time

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ..database import SessionLocal
from ..models import User
from ..ws_manager import auth_token, handle_ws_message, manager

router = APIRouter()

MEDIA_TYPES = {"call_audio", "screen_frame"}

# TEMP debug: счётчики media-сообщений по пользователям (аналог ws.py; убрать после диагностики)
_stats: dict[int, dict[str, int]] = {}


@router.get("/stream")
async def sse_stream(request: Request, token: str = ""):
    """SSE-поток входящих событий пользователя. Токен — в query (EventSource не умеет headers)."""
    user_id = auth_token(token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Неверный токен")

    db = SessionLocal()
    user = db.get(User, user_id)
    if user is None:
        db.close()
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    if getattr(user, "is_banned", False):
        db.close()
        raise HTTPException(status_code=403, detail="Заблокирован")

    user.is_online = True
    db.commit()
    for oid in manager.online_user_ids():
        await manager.send_to_user(oid, {"type": "status", "user_id": user_id, "online": True})

    q = manager.sse_connect(user_id)

    async def event_stream():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            manager.sse_disconnect(user_id, q)
            if not manager.is_online(user_id):
                user.is_online = False
                db.commit()
                for oid in manager.online_user_ids():
                    await manager.send_to_user(oid, {"type": "status", "user_id": user_id, "online": False})
            db.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.post("/push")
async def push_message(
    payload: dict,
    authorization: str = Header(default=""),
    token: str = Query(default=""),
):
    """Исходящее событие от клиента (сигналы/аудио звонка): тот же релей, что по WS."""
    if not token and authorization.lower().startswith("bearer "):
        token = authorization[7:]
    user_id = auth_token(token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Неверный токен")

    db = SessionLocal()
    user = db.get(User, user_id)
    if user is None:
        db.close()
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    if getattr(user, "is_banned", False):
        db.close()
        raise HTTPException(status_code=403, detail="Заблокирован")

    kind = payload.get("type")
    # TEMP debug: трассировка звонков по HTTP (убрать после диагностики)
    try:
        if kind in {"call", "call_offer", "call_answer", "call_ice", "call_hangup"}:
            print(
                f"[httpDBG] user {user_id} --> {kind} to_id={payload.get('to_id')} "
                f"room={payload.get('room_id')} at={time.strftime('%H:%M:%S')}",
                flush=True,
            )
        elif kind in MEDIA_TYPES:
            st = _stats.setdefault(user_id, {})
            st[kind] = st.get(kind, 0) + 1
            if st[kind] % 30 == 1:
                print(
                    f"[httpDBG] user {user_id} --> {kind}#{st[kind]} "
                    f"to_id={payload.get('to_id')} at={time.strftime('%H:%M:%S')}",
                    flush=True,
                )
        elif kind == "dbg":
            print(
                f"[httpDBG] user {user_id} DBG {json.dumps(payload)[:400]} at={time.strftime('%H:%M:%S')}",
                flush=True,
            )
    except Exception:
        pass

    try:
        err = await handle_ws_message(None, user_id, db, payload)
    except Exception as e:
        print(f"[http] user {user_id} handler error: {e!r}", flush=True)
        db.close()
        raise HTTPException(status_code=500, detail="Ошибка обработки")
    db.close()
    if err:
        raise HTTPException(status_code=400, detail=err.get("message", "Ошибка"))
    return {"ok": True}