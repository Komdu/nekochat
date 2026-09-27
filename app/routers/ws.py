import json
import time
import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..database import SessionLocal
from ..models import User
from ..ws_manager import auth_ws, handle_ws_message, manager

MEDIA_TYPES = {"call_audio", "screen_frame"}

# Туннель периодически рвёт WS (~2 мин на edge). Мгновенное «offline» на каждом
# обрыве делает присутствие мигающим у всех. Ждём грейс: если клиент вернулся —
# статус online не трогаем, фликра нет.
GRACE_OFFLINE_S = 10
_pending_offline: set[int] = set()


async def _mark_offline_after_grace(user_id: int):
    await asyncio.sleep(GRACE_OFFLINE_S)
    if manager.is_online(user_id):
        _pending_offline.discard(user_id)
        return
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user:
            user.is_online = False
            db.commit()
        # offline-статус — всем онлайн (WS + SSE + NATS)
        for oid in manager.online_user_ids():
            await manager.send_to_user(oid, {"type": "status", "user_id": user_id, "online": False})
    finally:
        db.close()
        _pending_offline.discard(user_id)

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    user_id = auth_ws(ws)
    if user_id is None:
        await ws.close(code=4401)
        return

    db = SessionLocal()
    user = db.get(User, user_id)
    if user is None:
        await ws.close(code=4401)
        db.close()
        return
    if getattr(user, "is_banned", False):
        await ws.close(code=4403)
        db.close()
        return

    user.is_online = True
    db.commit()

    await manager.connect(user_id, ws)
    _pending_offline.discard(user_id)  # вернулся в грейс-окно — офлайн отменяется
    # broadcast online status to everyone connected (WS + SSE)
    for oid in manager.online_user_ids():
        await manager.send_to_user(oid, {"type": "status", "user_id": user_id, "online": True})

    stats = {"t0": time.monotonic(), "msgs": 0, "media": 0, "bytes": 0, "kinds": {}}
    try:
        while True:
            text = await ws.receive_text()
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                continue
            kind = data.get("type")
            stats["msgs"] += 1
            stats["bytes"] += len(text)
            if kind in MEDIA_TYPES:
                stats["media"] += 1
            stats["kinds"][kind] = stats["kinds"].get(kind, 0) + 1
            # TEMP debug: трассировка звонков (убрать после диагностики)
            if kind in {"call", "call_offer", "call_answer", "call_ice", "call_hangup"}:
                print(
                    f"[wsDBG] user {user_id} --> {kind} to_id={data.get('to_id')} "
                    f"room={data.get('room_id')} at={time.strftime('%H:%M:%S')}",
                    flush=True,
                )
            elif kind in MEDIA_TYPES and (stats["kinds"][kind] % 30) == 1:
                print(
                    f"[wsDBG] user {user_id} --> {kind}#{stats['kinds'][kind]} "
                    f"to_id={data.get('to_id')} at={time.strftime('%H:%M:%S')}",
                    flush=True,
                )
            elif kind == "dbg":
                print(
                    f"[wsDBG] user {user_id} DBG {json.dumps(data)[:400]} at={time.strftime('%H:%M:%S')}",
                    flush=True,
                )
            try:
                err = await handle_ws_message(ws, user_id, db, data)
                if err:
                    try:
                        await ws.send_json(err)
                    except Exception:
                        pass
            except Exception as e:
                print(f"[ws] user {user_id} handler error: {e!r}", flush=True)
                stats["kinds"]["__handler_error__"] = stats["kinds"].get("__handler_error__", 0) + 1
    except WebSocketDisconnect as exc:
        # код закрытия: 1000/1001 — клиент, 1006 — сеть/прокси, 1011 — сервер.
        life = time.monotonic() - stats["t0"]
        print(
            f"[ws] user {user_id} disconnected: code={exc.code} reason={exc.reason!r} "
            f"life={life:.0f}s msgs={stats['msgs']} media={stats['media']} "
            f"bytes={stats['bytes']} kinds={stats['kinds']}",
            flush=True,
        )
    finally:
        manager.disconnect(user_id, ws)
        if not manager.is_online(user_id) and user_id not in _pending_offline:
            # офлайн — с задержкой: короткие обрывы туннеля не фликают presence
            _pending_offline.add(user_id)
            asyncio.create_task(_mark_offline_after_grace(user_id))
        db.close()