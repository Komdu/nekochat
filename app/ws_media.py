"""Бинарные каналы `/ws/media` и `/ws/transfer`.

Зачем это отдельные сокеты, а не всё в `/ws`:

* **Изоляция.** Файл на 50 МБ идёт по своему сокету. Он не может задержать
  голос или обычное сообщение — раньше всё сидело в одной очереди, и файл
  глушил звонок (head-of-line blocking).
* **Приоритеты.** У каждого соединения исходящая очередь разбита по классам
  (голос / control / видео / файл) и опустошается строго по приоритету. Если
  сеть не успевает, первым рвётся видео, потом файлы. Голос почти не рвётся.
* **Никакого base64.** Раньше аудио/видео ехали как base64 внутри JSON: +33%
  трафика и декод/енкод на каждом кадре на сервере и на клиенте. Теперь —
  сырые байты в бинарном фрейме.
* **Нет БД на кадр.** Раньше на каждом аудиокадре делался `db.get(Room)` и
  загружались участники — запрос к БД каждые 20 мс. Участники теперь кэшируются
  (`RoomMembers`) и инвалидируются при изменении состава.

Формат фрейма (little-endian, 12 байт заголовка):

    0   u8   version = 1
    1   u8   kind:  1=audio  2=video  3=file
    2   u16  flags: бит0 = room (иначе 1-1), бит1 = last
    4   u32  target (вверх: user_id/room_id) | from_id (вниз: кто прислал)
    8   u32  length — размер payload
    12  ...  payload (сырые байты Opus / видео / файловый чанк)

Формат симметричен в обе стороны: направление определяется сокетом, поэтому
парсер один и тот же.
"""

from __future__ import annotations

import asyncio
import struct
import time
from collections import deque
from dataclasses import dataclass, field

from fastapi import WebSocket

from .config import settings

# ---------------------------------------------------------------- константы

VER = 1
HDR = struct.Struct("<BBHII")  # version, kind, flags, target, length
HDR_SIZE = HDR.size            # 12
assert HDR_SIZE == 12

KIND_AUDIO = 1
KIND_VIDEO = 2
KIND_FILE = 3

FLAG_ROOM = 1 << 0
FLAG_LAST = 1 << 1

# Приоритет: меньше — важнее. Используется и в очереди, и в сортировке.
PRIO_VOICE = 0
PRIO_CTRL = 1
PRIO_VIDEO = 2
PRIO_FILE = 3

PRIO_BY_KIND = {KIND_AUDIO: PRIO_VOICE, KIND_VIDEO: PRIO_VIDEO, KIND_FILE: PRIO_FILE}

# какому сокету адресата принадлежит кадр: медиа-кадры -> /ws/media, файлы -> /ws/transfer
CHANNEL_BY_KIND = {KIND_AUDIO: "media", KIND_VIDEO: "media", KIND_FILE: "transfer"}


class FrameError(ValueError):
    """Битый или слишком большой фрейм."""


class IncompleteFrame(FrameError):
    """Заголовок получен, payload ещё в пути — данных пока недостаточно.

    Отличаем от мусора: буфер надо сохранить и подождать, а не сбрасывать.
    """


# ---------------------------------------------------------------- разбор фреймов


def parse_frame(buf: bytes | bytearray | memoryview) -> tuple[int, int, int, bytes]:
    """-> (kind, flags, target, payload). Бросает FrameError."""
    if len(buf) < HDR_SIZE:
        raise FrameError(f"короткий фрейм: {len(buf)} < {HDR_SIZE}")
    ver, kind, flags, target, length = HDR.unpack_from(buf, 0)
    if ver != VER:
        raise FrameError(f"версия {ver} != {VER}")
    if kind not in PRIO_BY_KIND:
        raise FrameError(f"неизвестный kind {kind}")
    maxlen = settings.media_max_frame
    if length > maxlen:
        raise FrameError(f"кадр {length} Б > потолка {maxlen}")
    end = HDR_SIZE + length
    if len(buf) < end:
        raise IncompleteFrame(f"неполный кадр: ждём {end}, есть {len(buf)}")
    # payload копируем: в буфере может лежать что-то ещё после кадра
    return kind, flags, target, bytes(memoryview(buf)[HDR_SIZE:end])


def build_frame(kind: int, flags: int, target: int, payload: bytes) -> bytes:
    return HDR.pack(VER, kind, flags, target, len(payload)) + payload


# ---------------------------------------------------------------- кэш участников


class RoomMembers:
    """Кэш «участники комнаты» для медиа-релея.

    Раньше на каждый кадр был запрос в БД. Кэш короткоживущий (30 c) и
    инвалидируется из routers/rooms.py при изменении состава.
    """

    def __init__(self) -> None:
        self._cache: dict[int, tuple[float, frozenset[int]]] = {}

    def invalidate(self, room_id: int) -> None:
        self._cache.pop(room_id, None)

    def get(self, room_id: int, db) -> frozenset[int] | None:
        ttl = settings.room_members_cache_s
        hit = self._cache.get(room_id)
        now = time.monotonic()
        if hit is not None and now - hit[0] < ttl:
            return hit[1]
        from .models import Room  # локальный импорт: не тянем ORM при старте

        room = db.get(Room, room_id)
        if room is None:
            self._cache[room_id] = (now, frozenset())
            return frozenset()
        members = frozenset(m.id for m in room.members)
        self._cache[room_id] = (now, members)
        return members


room_members = RoomMembers()


# ---------------------------------------------------------------- очереди


class OutQueue:
    """Исходящая очередь одного соединения с приоритетами и отбрасыванием.

    Не используем asyncio.Queue: он один и при переполнении роняет всё подряд.
    Здесь на каждый класс своя deque с потолком; при переполнении выкидываем
    самое старое из наименее важного класса. Релиз не трогаем.
    """

    def __init__(self, caps: dict[int, int]) -> None:
        self._caps = caps
        self._q: dict[int, deque] = {p: deque() for p in caps}
        self._sizes: dict[int, int] = {p: 0 for p in caps}
        self.dropped: dict[int, int] = {p: 0 for p in caps}
        self._wake = asyncio.Event()

    def put(self, prio: int, item: bytes) -> None:
        q = self._q[prio]
        q.append(item)
        self._sizes[prio] += len(item)
        cap = self._caps[prio]
        if len(q) > cap:
            self._drop_oldest(prio, len(q) - cap)
        self._wake.set()

    def _drop_oldest(self, prio: int, count: int) -> None:
        q = self._q[prio]
        for _ in range(min(count, len(q))):
            self._sizes[prio] -= len(q.popleft())
        self.dropped[prio] += count

    def depth(self, prio: int) -> int:
        return len(self._q[prio])

    def bytes(self, prio: int) -> int:
        return self._sizes[prio]

    def pop(self) -> bytes | None:
        """Достаёт кадр в порядке приоритета. None — пусто."""
        for prio in sorted(self._q):  # PRIO_VOICE -> PRIO_FILE
            q = self._q[prio]
            if q:
                item = q.popleft()
                self._sizes[prio] -= len(item)
                return item
        return None

    def clear(self) -> None:
        for prio in self._q:
            self._q[prio].clear()
            self._sizes[prio] = 0

    async def wait(self) -> None:
        await self._wake.wait()
        self._wake.clear()


# ---------------------------------------------------------------- соединение


@dataclass(eq=False)  # eq=False -> остаётся хеш по идентичности (нужен для set)
class MediaConn:
    """Одно бинарное соединение пользователя + его писатель."""

    user_id: int
    ws: WebSocket
    kind: str  # "media" | "transfer"
    q: OutQueue
    writer: asyncio.Task | None = None
    rx: int = 0            # принято кадров
    tx: int = 0            # отправлено кадров
    rx_bytes: int = 0
    tx_bytes: int = 0
    opened_at: float = field(default_factory=time.monotonic)

    def caps(self) -> dict[int, int]:
        s = settings
        if self.kind == "media":
            return {
                PRIO_VOICE: s.media_queue_voice,
                PRIO_VIDEO: s.media_queue_video,
                PRIO_CTRL: s.media_queue_ctrl,
            }
        # transfer: файлы — самый низкий приоритет, и их мало
        return {
            PRIO_VOICE: s.media_queue_voice,
            PRIO_CTRL: s.media_queue_ctrl,
            PRIO_FILE: s.media_queue_file,
        }

    def drain_stats(self) -> dict[int, int]:
        return {p: d for p, d in self.q.dropped.items() if d}


class MediaHub:
    """Реестр бинарных соединений + релей.

    Релей синхронный: `put_nowait` в чужую очередь. Ни одного await на сеть в
    горячем пути — это и есть причина, почему 50 МБ больше не душат звонок.
    """

    def __init__(self) -> None:
        self.conns: dict[str, dict[int, set[MediaConn]]] = {"media": {}, "transfer": {}}

    def add(self, conn: MediaConn) -> None:
        self.conns[conn.kind].setdefault(conn.user_id, set()).add(conn)

    def remove(self, conn: MediaConn) -> None:
        bucket = self.conns[conn.kind].get(conn.user_id)
        if bucket is not None:
            bucket.discard(conn)
            if not bucket:
                self.conns[conn.kind].pop(conn.user_id, None)

    def targets(self, kind: str, user_id: int) -> list[MediaConn]:
        return list(self.conns[kind].get(user_id, ()))

    # ---- релей ----

    def relay_to_user(self, user_id: int, kind: int, flags: int, src: int, payload: bytes) -> int:
        frame = build_frame(kind, flags, src, payload)
        prio = PRIO_BY_KIND[kind]
        conns = self.targets(CHANNEL_BY_KIND[kind], user_id)
        for c in conns:
            c.q.put(prio, frame)
        return len(conns)

    def relay_to_room(self, room_id: int, members: set[int], src: int, kind: int, flags: int, payload: bytes) -> int:
        frame = build_frame(kind, flags | FLAG_ROOM, src, payload)
        prio = PRIO_BY_KIND[kind]
        channel = CHANNEL_BY_KIND[kind]
        n = 0
        for uid in members:
            if uid == src:
                continue  # без эха отправителю
            for c in self.targets(channel, uid):
                c.q.put(prio, frame)
                n += 1
        return n

    def ctrl_to_user(self, user_id: int, payload: dict) -> int:
        """Служебное JSON-сообщение по бинарному сокету (ошибки квот и т.п.)."""
        import json

        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        frame = build_frame(KIND_FILE, 0, 0, raw)  # файловый слот: самый низкий приоритет
        conns = self.targets("transfer", user_id)
        for c in conns:
            c.q.put(PRIO_FILE, frame)
        return len(conns)

    # ---- статистика ----

    def stats(self) -> dict:
        out: dict = {"media": {}, "transfer": {}}
        for kind, users in self.conns.items():
            total_rx = total_tx = 0
            conns_n = 0
            dropped = 0
            for conns in users.values():
                for c in conns:
                    conns_n += 1
                    total_rx += c.rx
                    total_tx += c.tx
                    dropped += sum(c.q.dropped.values())
            out[kind] = {
                "conns": conns_n,
                "users": len(users),
                "rx": total_rx,
                "tx": total_tx,
                "dropped": dropped,
            }
        return out


hub = MediaHub()


# ---------------------------------------------------------------- писатель


async def writer_loop(conn: MediaConn) -> None:
    """Разбирает очередь в приоритетном порядке и шлёт в сокет.

    Между отправками уступаем циклу (await asyncio.sleep(0)), иначе плотный
    файловый поток съедает event loop и ломает приём на том же сокете.
    """
    q = conn.q
    while True:
        item = q.pop()
        if item is None:
            await q.wait()
            continue
        try:
            await conn.ws.send_bytes(item)
        except Exception:
            # сокет мёртв — дальше отправлять бессмысленно; разрыв догонит endpoint
            return
        conn.tx += 1
        conn.tx_bytes += len(item)
        await asyncio.sleep(0)
