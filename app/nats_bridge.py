"""NATS-транспорт (Phase 1): клиенты ходят по WSS через nats-server, мост — серверная часть релея.

Схема субъектов (префикс nkc = nekochat):
  nkc.in.<uid>    клиент -> сервер (сообщения/сигналы/аудио/ping)
  nkc.out.<uid>   сервер -> клиент (события — те же, что шли бы по /ws; клиент подписан)

Presence: юзер "online" с первого входящего сообщения, "offline" — после
NATS_SILENCE_S тишины (это и есть half-open guard: мёртвый сокет больше не
держится за online). Обработка сообщений — та же handle_ws_message(None, uid, db, payload),
что и в /push (http_stream), т.е. семантика комнат/сообщений/звонков не меняется.

Откат: NATS_ENABLED=false полностью отключает мост (всё работает как раньше на /ws).
"""
import asyncio
import json
import time

import nats

from .config import settings
from .database import SessionLocal
from .models import User
from .ws_manager import handle_ws_message, manager


class NatsBridge:
    def __init__(self):
        self.nc = None
        self._sub = None
        self._tasks: list[asyncio.Task] = []
        self._workers: dict[int, asyncio.Task] = {}  # uid -> out-воркер
        self.live: set[int] = set()                  # uid, считающиеся online по NATS
        self.last_seen: dict[int, float] = {}        # uid -> monotonic() последнего сообщения
        self._in_stats: dict[int, dict[str, int]] = {}  # TEMP debug (убрать после диагностики)

    # ---------------- lifecycle ----------------

    async def start(self):
        if not settings.nats_enabled:
            print("[nats] мост ОТКЛЮЧЁН (NATS_ENABLED=false)", flush=True)
            return
        try:
            self.nc = await self._connect_once()
        except Exception as e:
            print(f"[nats] стартовый коннект не удался ({e!r}) — подключусь в фоне", flush=True)
            self._tasks.append(asyncio.create_task(self._connect_loop()))
            return
        await self._after_connect()

    async def _connect_once(self):
        return await nats.connect(
            settings.nats_url,
            user=settings.nats_ws_user,
            password=settings.nats_ws_pass,
            name="nekochat-bridge",
            connect_timeout=3,
            max_reconnect_attempts=-1,
            reconnect_time_wait=2,
            allow_reconnect=True,
        )

    async def _connect_loop(self):
        while True:
            try:
                self.nc = await self._connect_once()
                print("[nats] мост подключён (фон)", flush=True)
                await self._after_connect()
                return
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"[nats] background connect retry: {e!r}", flush=True)
                await asyncio.sleep(3)

    async def _after_connect(self):
        self._tasks.append(asyncio.create_task(self._inbound_loop()))
        self._tasks.append(asyncio.create_task(self._silence_loop()))
        print(f"[nats] мост подключён к {settings.nats_url}", flush=True)

    async def stop(self):
        if self._sub is not None:
            try:
                await self._sub.unsubscribe()
            except Exception:
                pass
            self._sub = None
        for w in list(self._workers.values()):
            w.cancel()
        self._workers.clear()
        for t in self._tasks:
            t.cancel()
        self._tasks.clear()
        if self.nc is not None:
            try:
                await self.nc.close()
            except Exception:
                pass
            self.nc = None
        print("[nats] мост остановлен", flush=True)

    # ---------------- inbound ----------------

    async def _inbound_loop(self):
        while True:
            try:
                sub = await self.nc.subscribe("nkc.in.>")
                self._sub = sub
                print("[nats] слушаю nkc.in.*", flush=True)
                async for msg in sub.messages:
                    try:
                        await self._handle_in(msg)
                    except Exception as e:
                        print(f"[nats] inbound error: {e!r}", flush=True)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"[nats] inbound loop restart: {e!r}", flush=True)
                await asyncio.sleep(2)

    async def _handle_in(self, msg):
        # subject = nkc.in.<uid>
        try:
            uid = int(msg.subject.rsplit(".", 1)[1])
        except (ValueError, IndexError):
            return
        try:
            payload = json.loads(msg.data.decode("utf-8"))
        except Exception:
            return
        if not isinstance(payload, dict):
            return

        is_new = self._touch(uid)
        if is_new:
            await self._broadcast_online(uid)

        # TEMP debug — счётчики сигналов/аудио (аналог [wsDBG]/[httpDBG])
        kind = payload.get("type")
        if kind in ("call", "call_answer", "call_hangup", "call_audio", "screen_frame"):
            st = self._in_stats.setdefault(uid, {})
            st[kind] = st.get(kind, 0) + 1
            if kind == "call_audio" and st[kind] % 30 == 1:
                print(
                    f"[natsDBG] user {uid} --> {kind}#{st[kind]} "
                    f"to_id={payload.get('to_id')} at={time.strftime('%H:%M:%S')}",
                    flush=True,
                )

        db = SessionLocal()
        try:
            user = db.get(User, uid)
            if user is None or getattr(user, "is_banned", False):
                return
            err = await handle_ws_message(None, uid, db, payload)
        except Exception as e:
            print(f"[nats] user {uid} handler error: {e!r}", flush=True)
            return
        finally:
            db.close()
        if err:
            await self.publish_to(uid, err)

    def _touch(self, uid: int) -> bool:
        """Обновляет last_seen. True — если юзер перешёл offline->online (нужна рассылка)."""
        now = time.monotonic()
        self.last_seen[uid] = now
        if uid in self.live:
            return False
        self.live.add(uid)
        q = manager.nats.get(uid) or manager.nats_connect(uid)
        self._workers[uid] = asyncio.create_task(self._out_worker(uid, q))
        return True

    async def _broadcast_online(self, uid: int):
        db = SessionLocal()
        try:
            user = db.get(User, uid)
            if user is not None:
                user.is_online = True
                db.commit()
        finally:
            db.close()
        for oid in manager.online_user_ids():
            if oid != uid:
                await manager.send_to_user(oid, {"type": "status", "user_id": uid, "online": True})
        print(f"[natsDBG] user {uid} online (NATS)", flush=True)

    # ---------------- presence / half-open guard ----------------

    async def _silence_loop(self):
        while True:
            await asyncio.sleep(5)
            now = time.monotonic()
            for uid in list(self.live):
                if now - self.last_seen.get(uid, 0) <= settings.nats_silence_s:
                    continue
                # тишина дольше порога -> считаем offline и выкидываем (мёртвый сокет не держим)
                self.live.discard(uid)
                self.last_seen.pop(uid, None)
                w = self._workers.pop(uid, None)
                if w is not None:
                    w.cancel()
                manager.nats_disconnect(uid)
                if not manager.is_online(uid):
                    db = SessionLocal()
                    try:
                        user = db.get(User, uid)
                        if user is not None:
                            user.is_online = False
                            db.commit()
                    finally:
                        db.close()
                    for oid in manager.online_user_ids():
                        if oid != uid:
                            await manager.send_to_user(
                                oid, {"type": "status", "user_id": uid, "online": False}
                            )
                    print(f"[natsDBG] user {uid} offline (silence {settings.nats_silence_s}s)", flush=True)

    # ---------------- outbound ----------------

    async def _out_worker(self, uid: int, q: asyncio.Queue):
        while True:
            try:
                payload = await q.get()
            except asyncio.CancelledError:
                return
            nc = self.nc
            if nc is None:
                await asyncio.sleep(0.5)
                continue
            try:
                await nc.publish(
                    f"nkc.out.{uid}", json.dumps(payload, ensure_ascii=False).encode("utf-8")
                )
            except Exception:
                await asyncio.sleep(0.5)

    async def publish_to(self, uid: int, payload: dict):
        """Прямая публикация (полезно для ответа на ошибки а-ля ws.send_json)."""
        nc = self.nc
        if nc is None:
            return
        try:
            await nc.publish(
                f"nkc.out.{uid}", json.dumps(payload, ensure_ascii=False).encode("utf-8")
            )
        except Exception:
            pass


nats_bridge = NatsBridge()