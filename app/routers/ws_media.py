"""Эндпоинты бинарных каналов: `/ws/media` (аудио+видео) и `/ws/transfer` (файлы).

Оба — чистый релей: сервер не хранит ни байта. `/ws` остаётся каналом
управления (presence, сообщения, сигналинг звонков) в JSON.

Приём сокета: WS-сообщения могут приходить склеенными, поэтому накапливаем буфер
и вычитываем кадры, пока они есть. Наружу отдаёт writer_loop с приоритетами
(см. app/ws_media.py).
"""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal
from ..models import User
from ..ws_manager import auth_ws
from ..ws_media import (
    FLAG_ROOM,
    HDR_SIZE,
    KIND_AUDIO,
    KIND_FILE,
    KIND_VIDEO,
    FrameError,
    MediaConn,
    OutQueue,
    hub,
    parse_frame,
    unpack_flags,
    room_members,
    writer_loop,
)
from ..ws_media import IncompleteFrame

router = APIRouter()

TRANSFER_ALLOWED_KINDS = (KIND_FILE,)
MEDIA_ALLOWED_KINDS = (KIND_AUDIO, KIND_VIDEO)

# сколько ждём следующего сообщения, прежде чем считать соединение мёртвым
IDLE_WATCHDOG_S = 90


async def _auth(ws: WebSocket) -> int | None:
    """Авторизация по ?token=, как в /ws. Возвращает user_id или None."""
    user_id = auth_ws(ws)
    if user_id is None:
        return None
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user is None or getattr(user, "is_banned", False):
            return None
    finally:
        db.close()
    return user_id


class _Members:
    """Ленивая выборка участников комнаты: сессия БД открывается только на
    промах кэша, а не на каждый кадр."""

    def __init__(self) -> None:
        self._db: Session | None = None

    def get(self, room_id: int) -> set[int] | None:
        cached = room_members._cache.get(room_id)  # noqa: SLF001 — свой же модуль
        if cached is not None and time.monotonic() - cached[0] < settings.room_members_cache_s:
            return set(cached[1])
        if self._db is None:
            self._db = SessionLocal()
        try:
            members = room_members.get(room_id, self._db)
        except Exception:
            self._db.close()
            self._db = None
            return None
        return set(members) if members is not None else None

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None


async def _serve_channel(ws: WebSocket, channel: str) -> None:
    user_id = await _auth(ws)
    if user_id is None:
        await ws.close(code=4401)
        return

    await ws.accept()

    probe = MediaConn(user_id=user_id, ws=ws, kind=channel, q=OutQueue({}))
    conn = MediaConn(
        user_id=user_id,
        ws=ws,
        kind=channel,
        q=OutQueue(probe.caps()),
    )
    conn.writer = asyncio.create_task(writer_loop(conn))
    hub.add(conn)

    allowed = MEDIA_ALLOWED_KINDS if channel == "media" else TRANSFER_ALLOWED_KINDS
    members = _Members()
    buf = bytearray()
    err_frames = dropped = relayed = 0
    reason = "closed"
    try:
        while True:
            try:
                message = await asyncio.wait_for(ws.receive(), timeout=IDLE_WATCHDOG_S)
            except asyncio.TimeoutError:
                # тишина в сокете — держим соединение живым «пингом» от сервера
                reason = "idle"
                break
            if message.get("type") == "websocket.disconnect":
                code = message.get("code", 1006)
                reason = f"disconnect:{code}"
                break

            data = message.get("bytes")
            if data is None:
                # текст на бинарном сокете — мусор, игнорируем
                continue
            buf += data
            conn.rx_bytes += len(data)

            # вычитываем все кадры, сколько есть в буфере
            while len(buf) >= HDR_SIZE:
                try:
                    kind, flags, target, payload = parse_frame(buf)
                except IncompleteFrame:
                    # payload ещё в пути — ждём следующий receive, буфер цел
                    break
                except FrameError:
                    err_frames += 1
                    if err_frames > 16:
                        reason = "bad-frames"
                        return
                    # мусор/рассинхрон — сбрасываем буфер, а не копим мусор
                    buf.clear()
                    break
                del buf[: HDR_SIZE + len(payload)]
                conn.rx += 1
                if kind not in allowed:
                    continue

                room_mode = bool(flags & FLAG_ROOM)
                _, is_last, stream = unpack_flags(flags)

                # Файлы идут через квоту (transfer_max_files_per_user): лишние
                # вежливо не пропускаем — файл одноразовый, попросят ещё раз.
                if kind == KIND_FILE:
                    fkey = target if room_mode else 0
                    if not hub.admit_file(user_id, stream, fkey):
                        continue
                else:
                    stream = 0

                if room_mode:
                    mset = members.get(target)
                    if mset is None or user_id not in mset:
                        if kind == KIND_FILE:
                            hub.close_file(user_id, stream, target)
                        continue  # не комната / не участник
                    relayed += hub.relay_to_room(target, mset, user_id, kind, flags, payload)
                else:
                    if target == user_id:
                        if kind == KIND_FILE:
                            hub.close_file(user_id, stream, 0)
                        continue  # эхо себе не нужно
                    relayed += hub.relay_to_user(target, kind, flags, user_id, payload)

                if kind == KIND_FILE and is_last:
                    hub.close_file(user_id, stream, target if room_mode else 0)

            # буфер не должен расти бесконечно: если кто-то шлёт заголовки без payload
            if len(buf) > settings.media_max_frame + HDR_SIZE:
                err_frames += 1
                buf.clear()
    except WebSocketDisconnect as exc:
        reason = f"disconnect:{exc.code}"
    except Exception as e:  # noqa: BLE001 — не роняем сервер из-за одного сокета
        reason = f"error:{e!r}"
    finally:
        life = time.monotonic() - conn.opened_at
        print(
            f"[{channel}] user {user_id} {reason} life={life:.0f}s rx={conn.rx} "
            f"tx={conn.tx} rxKB={conn.rx_bytes // 1024} txKB={conn.tx_bytes // 1024} "
            f"relayed={relayed} dropped={dropped} bad={err_frames}",
            flush=True,
        )
        hub.remove(conn)
        if channel == "transfer":
            hub.drop_user_files(user_id)
        conn.q.clear()
        if conn.writer is not None:
            conn.writer.cancel()
        members.close()


@router.websocket("/ws/media")
async def ws_media(ws: WebSocket) -> None:
    if not settings.media_socket_enabled:
        await ws.close(code=4404)
        return
    await _serve_channel(ws, "media")


@router.websocket("/ws/transfer")
async def ws_transfer(ws: WebSocket) -> None:
    if not settings.transfer_socket_enabled:
        await ws.close(code=4404)
        return
    await _serve_channel(ws, "transfer")


@router.get("/api/ws-stats")
async def ws_stats() -> dict:
    """Диагностика релея: сколько соединений, кадров и сколько отброшено.

    Помогает понять, упираемся ли мы в туннель (relay растёт, dropped 0)
    или в клиент/сеть (dropped растёт).
    """
    s = hub.stats()
    return {
        "media": s["media"],
        "transfer": s["transfer"],
        "file_streams": s["file_streams"],
        "quota_rejects": s["quota_rejects"],
        # накопительные за всё время работы процесса: не обнуляются при отключениях
        "total_rx": s["total_rx"],
        "total_tx": s["total_tx"],
        "total_dropped": s["total_dropped"],
    }
