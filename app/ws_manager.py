from datetime import datetime
import asyncio

from fastapi import WebSocket
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from .config import settings


class ConnectionManager:
    def __init__(self):
        # user_id -> set of websockets
        self.active: dict[int, set[WebSocket]] = {}
        # user_id -> set of SSE-очередей (HTTP-транспорт: GET /stream)
        self.sse: dict[int, set[asyncio.Queue]] = {}
        # user_id -> out-очередь для NATS-транспорта (клиент подписан на nkc.out.<uid>)
        self.nats: dict[int, asyncio.Queue] = {}

    async def connect(self, user_id: int, ws: WebSocket):
        await ws.accept()
        self.active.setdefault(user_id, set()).add(ws)

    def disconnect(self, user_id: int, ws: WebSocket):
        sockets = self.active.get(user_id)
        if sockets:
            sockets.discard(ws)
            if not sockets:
                self.active.pop(user_id, None)

    def sse_connect(self, user_id: int) -> asyncio.Queue:
        """Регистрирует SSE-подписку пользователя, возвращает его очередь событий."""
        q: asyncio.Queue = asyncio.Queue(maxsize=512)
        self.sse.setdefault(user_id, set()).add(q)
        return q

    def sse_disconnect(self, user_id: int, q: asyncio.Queue):
        queues = self.sse.get(user_id)
        if queues:
            queues.discard(q)
            if not queues:
                self.sse.pop(user_id, None)

    def nats_connect(self, user_id: int) -> asyncio.Queue:
        """Регистрирует NATS-подписку пользователя, возвращает out-очередь."""
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self.nats[user_id] = q
        return q

    def nats_disconnect(self, user_id: int):
        self.nats.pop(user_id, None)

    def nats_queue(self, user_id: int) -> asyncio.Queue | None:
        return self.nats.get(user_id)

    def online_user_ids(self) -> set[int]:
        return set(self.active.keys()) | set(self.sse.keys()) | set(self.nats.keys())

    async def broadcast(self, payload: dict, exclude: set[int] | None = None):
        """Разослать всем на связи. Нужно для присутствия: сменил человек
        статус — узнать об этом должны все, а не только тот, кто его спросил.

        exclude — тех, кто уже знает (обычно сам автор: он и так видит свой
        профиль)."""
        skip = exclude or set()
        targets = (set(self.active) | set(self.sse) | set(self.nats)) - skip
        if not targets:
            return 0
        sent = 0
        for uid in list(targets):
            try:
                await self.send_to_user(uid, payload)
                sent += 1
            except Exception:
                # один мёртвый сокет не должен ронять рассылку остальным
                continue
        return sent

    async def send_to_user(self, user_id: int, payload: dict):
        sockets = list(self.active.get(user_id, set()))
        queues = list(self.sse.get(user_id, set()))
        if not sockets and not queues:
            return
        # WS-часть — параллельно + с таймаутом: один полумёртвый сокет собеседника не
        # должен замораживать раздачу (раньше последовательный await блокировал релей
        # звонка на первом же зависшем соединении — см. media=839 vs 30).
        await asyncio.gather(*(self._send_guarded(ws, payload) for ws in sockets))
        # SSE-часть — пишем в очереди синхронно (put_nowait), без ожидания сети.
        for q in queues:
            try:
                if q.full():
                    q.get_nowait()  # переполнение: старейшее событие — в топку (аудио это переживёт)
                q.put_nowait(payload)
            except Exception:
                pass
        # NATS-часть — та же очередь на юзера (флудит мост в nkc.out.<uid>).
        qn = self.nats.get(user_id)
        if qn is not None:
            try:
                if qn.full():
                    qn.get_nowait()
                qn.put_nowait(payload)
            except Exception:
                pass

    async def _send_guarded(self, ws: WebSocket, payload: dict):
        try:
            await asyncio.wait_for(ws.send_json(payload), timeout=0.5)
        except Exception:
            pass  # мёртвый/медленный сокет — пропускаем, остальные получат

    def is_online(self, user_id: int) -> bool:
        return bool(self.active.get(user_id) or self.sse.get(user_id) or self.nats.get(user_id))


manager = ConnectionManager()


# Главный event loop сервера. Нужен, чтобы из СИНХРОННЫХ эндпоинтов отправлять
# асинхронные рассылки: FastAPI выполняет sync-обработчики в пуле потоков, где
# get_running_loop() падает. Без этого молча теряется всё, что разослать из
# /users/me/profile — то есть смена статуса, имени или аватарки.
_loop: asyncio.AbstractEventLoop | None = None


def set_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def spawn(coro) -> bool:
    """Запустить корутину из чужого потока, не дожидаясь её.

    Именно run_coroutine_threadsafe, а не create_task: вызов приходит из пула
    потоков, а не с event loop.
    """
    if _loop is None or _loop.is_closed():
        coro.close()
        return False
    try:
        asyncio.run_coroutine_threadsafe(coro, _loop)
        return True
    except RuntimeError:
        coro.close()
        return False


def auth_token(token: str | None) -> int | None:
    """Validate JWT token (query/header) and return user id."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        return None


def auth_ws(ws: WebSocket) -> int | None:
    """Extract and validate token from query param."""
    return auth_token(ws.query_params.get("token"))


async def handle_ws_message(ws: WebSocket | None, user_id: int, db: Session, data: dict):
    """Обработка входящего события. Возвращает None при успехе или dict-ошибку
    {'type':'error', ...}, которую вызывающий (WS или HTTP) отдаёт клиенту."""
    from .models import DirectConversation, DirectMessage, Message, Room

    kind = data.get("type")
    if kind == "room_message":
        room_id = data.get("room_id")
        content = data.get("content", "")
        if not content.strip():
            return None
        room = db.get(Room, room_id)
        if not room or user_id not in [m.id for m in room.members]:
            return {"type": "error", "message": "Not a member"}
        msg = Message(room_id=room_id, user_id=user_id, content=content)
        db.add(msg)
        db.commit()
        db.refresh(msg)
        payload = {
            "type": "room_message",
            "room_id": room_id,
            "message": {
                "id": msg.id,
                "content": msg.content,
                "created_at": msg.created_at.isoformat(),
                "user_id": user_id,
            },
        }
        for member in room.members:
            await manager.send_to_user(member.id, payload)

    elif kind == "direct_message":
        to_id = data.get("to_id")
        content = data.get("content", "")
        if not content.strip() or not to_id:
            return
        # canonical pair
        a, b = sorted([user_id, to_id])
        conv = (
            db.query(DirectConversation)
            .filter(
                (DirectConversation.user_a_id == a) & (DirectConversation.user_b_id == b)
            )
            .first()
        )
        if conv is None:
            conv = DirectConversation(user_a_id=a, user_b_id=b)
            db.add(conv)
            db.commit()
            db.refresh(conv)
        msg = DirectMessage(conversation_id=conv.id, sender_id=user_id, content=content)
        db.add(msg)
        db.commit()
        db.refresh(msg)
        payload = {
            "type": "direct_message",
            "conversation_id": conv.id,
            "from_id": user_id,
            "message": {
                "id": msg.id,
                "content": msg.content,
                "created_at": msg.created_at.isoformat(),
                "sender_id": user_id,
            },
        }
        await manager.send_to_user(user_id, payload)
        await manager.send_to_user(to_id, payload)

    elif kind == "call" or kind == "call_offer" or kind == "call_answer" or kind == "call_ice" or kind == "call_hangup" \
            or kind == "screen_start" or kind == "screen_stop":
        # Generic signaling relay. For 1-1: to_id. For room calls: broadcast to room members.
        payload = {**data, "from_id": user_id}
        call_to = data.get("to_id")
        room_id = data.get("room_id")
        if call_to is not None:
            await manager.send_to_user(user_id, payload)
            await manager.send_to_user(call_to, payload)
        elif room_id is not None:
            room = db.get(Room, room_id) if room_id else None
            if room is None or user_id not in [m.id for m in room.members]:
                return {"type": "error", "message": "Not a member"}
            for member in room.members:
                await manager.send_to_user(member.id, payload)
        else:
            return {"type": "error", "message": "Missing to_id or room_id"}

    elif kind == "call_audio" or kind == "screen_frame":
        # Аудио/видео звонка (Opus по WS/HTTP / видео-кадры): сервер — только реле, без эха отправителю.
        payload = {**data, "from_id": user_id}
        call_to = data.get("to_id")
        room_id = data.get("room_id")
        if call_to is not None:
            await manager.send_to_user(call_to, payload)
        elif room_id is not None:
            room = db.get(Room, room_id) if room_id else None
            if room is None or user_id not in [m.id for m in room.members]:
                return {"type": "error", "message": "Not a member"}
            for member in room.members:
                if member.id != user_id:
                    await manager.send_to_user(member.id, payload)
        else:
            return {"type": "error", "message": "Missing to_id or room_id"}

    elif kind == "ping":
        if ws is not None:
            await ws.send_json({"type": "pong"})
        else:
            # NATS/HTTP-транспорт: pong в out-очередь пользователя (клиент меряет RTT)
            await manager.send_to_user(user_id, {"type": "pong"})

    return None
