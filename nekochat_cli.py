#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""nekochat_cli — headless WS-клиент для диагностики звонкового релея.

Вопрос, на который отвечает: виноват ли WS-клиент нашего десктопа
(WebView2/WebAudio), или сам WS-канал/сервер/сеть?

CLI говорит с продом теми же сообщениями, что и десктоп (по /ws?token=JWT),
но без браузера. Измеряет:
  - целостность потока call_audio: дыры в seq, перестановки, дубли;
  - скорость приёма (fps) и разброс интервалов;
  - RTT по WS ping/pong (протокол, не приложение);
  - любые ошибки отправки и WS-закрытия.

Использование:
  nekochat_cli.py login  --user U --pass P [--url https://...]
  nekochat_cli.py caller --user U --pass P --peer 13 [--rate 50] [--duration 120]
  nekochat_cli.py callee --user U --pass P                  [--rate 50] [--duration 120]
  nekochat_cli.py ping   --user U --pass P [--count 50]
  nekochat_cli.py nats-ping --user U --pass P [--count 50]   # NATS-транспорт (wss://…/nats)

Токен из login кешируется в ./nekochat_cli.token (или передайте --token).
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import statistics
import sys
import time
import urllib.request

import websockets

# Windows-консоль по умолчанию cp1252 — переключаем потоки на UTF-8,
# иначе кириллица валит даже --help.
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_URL = "https://nekochat.komdu.is-cool.dev"
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nekochat_cli.token")
DEFAULT_RATE = 50  # кадров/с (один кадр = одно WS-сообщение, как десктоп)


class Cli:
    def __init__(self, args):
        self.args = args
        self.me_id: int | None = None
        self.peer_id: int | None = None
        self.call_id: str | None = None
        self.ws = None
        self.phase = "idle"  # idle|outgoing|incoming|active|ended
        # stream counters
        self.sent = 0
        self.send_errors = 0
        self.received = 0
        self.gaps = 0
        self.max_gap = 0
        self.reorders = 0
        self.dups = 0
        self.last_seq: int | None = None
        self.arrivals: list[float] = []
        self.rtts: list[float] = []
        self.stop = False
        self.t0 = 0.0
        self.finished_reason = ""

    # ---------- auth ----------

    def login(self) -> str:
        url = f"{self.args.url}/auth/login"
        body = json.dumps({"username": self.args.user, "password": self.args.password}).encode()
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
        token = data["access_token"]
        self.me_id = int(data["user"]["id"])
        print(f"[cli] login OK: user {self.me_id} ({data['user']['username']})", flush=True)
        return token

    def get_token(self) -> str:
        if self.args.token:
            return self.args.token
        token = self.login()
        try:
            with open(TOKEN_FILE, "w") as f:
                f.write(token)
        except OSError:
            pass
        return token

    # ---------- ws ----------

    async def connect(self) -> None:
        token = self.get_token()
        base = self.args.url.replace("https://", "wss://").replace("http://", "ws://")
        uri = f"{base}/ws?token={token}"
        print(f"[cli] ws connect {base}/ws?...", flush=True)
        self.ws = await websockets.connect(uri, ping_interval=None, close_timeout=5)
        print("[cli] ws connected", flush=True)

    async def send(self, payload: dict) -> bool:
        if self.ws is None:
            return False
        try:
            await self.ws.send(json.dumps(payload))
            return True
        except Exception as e:
            self.send_errors += 1
            print(f"[cli] SEND ERROR: {e!r}", flush=True)
            return False

    # ---------- синтетическое аудио ----------

    def _audio_payload(self, seq: int) -> str:
        # Реалистичный опус-подобный кадр: 20-60 Б, детерминированный паттерн.
        n = 20 + (seq % 40)
        raw = bytes(((seq >> 8) & 0xFF, seq & 0xFF)) + bytes(n - 2)
        return base64.b64encode(raw).decode()

    # ---------- обработка входящих ----------

    def _on_ws_message(self, data: dict) -> None:
        ty = data.get("type")
        from_id = data.get("from_id")
        if ty == "call_audio":
            if self.phase not in ("connecting", "active", "outgoing"):
                return
            seq = int(data.get("seq", 0))
            now = time.monotonic()
            self.received += 1
            self.arrivals.append(now)
            if self.last_seq is not None:
                delta = seq - self.last_seq
                if delta == 0:
                    self.dups += 1
                elif delta < 0:
                    self.reorders += 1
                elif delta > 1:
                    self.gaps += 1
                    self.max_gap = max(self.max_gap, delta)
            self.last_seq = seq
            return
        if ty == "call_answer":
            if (
                from_id is not None and from_id == self.peer_id
                and self.call_id and data.get("call_id") == self.call_id
            ):
                self.phase = "active"
                print("[cli] ^ call_answer — call active", flush=True)
            return
        if ty == "call_hangup":
            if from_id is not None and (from_id == self.peer_id or from_id == self.me_id):
                print(f"[cli] ^ call_hangup reason={data.get('reason')}", flush=True)
                self.phase = "ended"
                self.finished_reason = f"hangup({data.get('reason')})"
            return
        if ty == "error":
            print(f"[cli] ^ server error: {data}", flush=True)
            return
        # status / direct_message / room_message / ping / pong — игнор

    # ---------- команды ----------

    async def cmd_ping(self) -> None:
        # Прикладной ping ({"type":"ping"} -> {"type":"pong"}) — ровно как у десктопа
        # (run.py: протокольные ping/pong через cloudflared ненадёжны, liveness на
        # уровне приложения). Протокольный ws.ping() тут намеренно НЕ используем.
        await self.connect()
        seq = 0
        try:
            for i in range(self.args.count):
                t0 = time.monotonic()
                await self.send({"type": "ping", "seq": seq})
                seq += 1
                got = False
                while True:
                    try:
                        msg = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=self.args.ping_timeout))
                    except asyncio.TimeoutError:
                        break
                    if msg.get("type") == "pong":
                        rtt = (time.monotonic() - t0) * 1000
                        self.rtts.append(rtt)
                        tag = "  <-- STALL" if rtt > 1000 else ""
                        print(f"[cli] ping #{i}: {rtt:.1f} ms{tag}", flush=True)
                        got = True
                        break
                if not got:
                    print(f"[cli] ping #{i}: TIMEOUT ({self.args.ping_timeout}s) — канал 'молчит'", flush=True)
                await asyncio.sleep(self.args.ping_gap)
        except Exception as e:
            print(f"[cli] ping loop error: {e!r}", flush=True)
        finally:
            try:
                await self.ws.close()
            except Exception:
                pass
        if self.rtts:
            print(
                f"[cli] RTT: min={min(self.rtts):.1f} med={statistics.median(self.rtts):.1f} "
                f"max={max(self.rtts):.1f} ms (n={len(self.rtts)})",
                flush=True,
            )

    async def cmd_nats_ping(self) -> None:
        """RTT по NATS-транспорту: nats-server по WSS того же туннеля.

        Клиент: креды из REST /nats/creds, подписка nkc.out.<uid>, публикация
        nkc.in.<uid> {"type":"ping"} — сервер отвечает {"type":"pong"} (как /ws).
        """
        import nats  # локальный импорт: nats-py нужен только этой команде

        token = self.get_token()
        req = urllib.request.Request(
            f"{self.args.url}/nats/creds",
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            c = json.loads(r.read().decode())
        url = c["url"]  # wss://host/nats
        print(f"[nats] connecting {url} user={c['user']} uid={c['uid']}", flush=True)
        nc = await nats.connect(
            url,
            user=c["user"],
            password=c["password"],
            name="nekochat-cli-nats",
            connect_timeout=15,
            max_reconnect_attempts=2,
            allow_reconnect=True,
        )
        print("[nats] connected", flush=True)
        sub = await nc.subscribe(f"nkc.out.{c['uid']}")
        uid = c["uid"]
        try:
            for i in range(self.args.count):
                t0 = time.monotonic()
                await nc.publish(f"nkc.in.{uid}", json.dumps({"type": "ping", "seq": i}).encode())
                got = False
                deadline = time.monotonic() + self.args.ping_timeout
                while time.monotonic() < deadline:
                    try:
                        msg = await sub.next_msg(timeout=deadline - time.monotonic())
                    except Exception:
                        break
                    data = json.loads(msg.data.decode())
                    if data.get("type") == "pong":
                        rtt = (time.monotonic() - t0) * 1000
                        self.rtts.append(rtt)
                        tag = "  <-- STALL" if rtt > 1000 else ""
                        print(f"[nats] ping #{i}: {rtt:.1f} ms{tag}", flush=True)
                        got = True
                        break
                if not got:
                    print(f"[nats] ping #{i}: TIMEOUT ({self.args.ping_timeout}s) — канал 'молчит'", flush=True)
                await asyncio.sleep(self.args.ping_gap)
        except Exception as e:
            print(f"[nats] ping loop error: {e!r}", flush=True)
        finally:
            try:
                await nc.close()
            except Exception:
                pass
        if self.rtts:
            print(
                f"[nats] RTT: min={min(self.rtts):.1f} med={statistics.median(self.rtts):.1f} "
                f"max={max(self.rtts):.1f} ms (n={len(self.rtts)})",
                flush=True,
            )

    async def cmd_caller(self) -> None:
        self.peer_id = self.args.peer
        await self.connect()
        self.call_id = f"cli-c{int(time.time() * 1000)}"
        self.phase = "outgoing"
        await self.send({"type": "call", "to_id": self.peer_id, "call_id": self.call_id})
        print(f"[cli] --> call to {self.peer_id} call_id={self.call_id}", flush=True)
        await self._run_common()

    async def cmd_callee(self) -> None:
        await self.connect()
        self.phase = "incoming"
        print("[cli] callee: жду входящий call...", flush=True)
        deadline = time.monotonic() + (self.args.wait or 60)
        accepted = False
        while time.monotonic() < deadline:
            try:
                msg = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=1))
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"[cli] callee WS closed: {e!r}", flush=True)
                return
            if msg.get("type") == "call" and msg.get("to_id") == self.me_id:
                self.peer_id = msg.get("from_id")
                self.call_id = msg.get("call_id")
                print(f"[cli] ^ incoming call from {self.peer_id} call_id={self.call_id}", flush=True)
                if self.args.answer_ms:
                    await asyncio.sleep(self.args.answer_ms / 1000)
                await self.send({"type": "call_answer", "to_id": self.peer_id, "call_id": self.call_id})
                print("[cli] --> call_answer (accepted)", flush=True)
                self.phase = "active"
                accepted = True
                break
        if not accepted:
            print("[cli] callee: входящий так и не пришёл", flush=True)
            try:
                await self.ws.close()
            except Exception:
                pass
            return
        await self._run_common()

    async def _run_common(self) -> None:
        """После установления/в ожидании — гоняем аудио и считаем."""
        self.t0 = time.monotonic()
        sender = asyncio.create_task(self._sender())
        receiver = asyncio.create_task(self._receiver())
        try:
            timeout = self.args.duration or 0
            if timeout:
                await asyncio.sleep(timeout)
                if self.phase == "active":
                    await self.send({"type": "call_hangup", "to_id": self.peer_id, "call_id": self.call_id, "reason": "ended"})
                self.phase = "ended"
                self.finished_reason = f"timeout({timeout}s)"
            else:
                while self.phase != "ended":
                    await asyncio.sleep(0.2)
                await asyncio.sleep(1.0)  # дать домчаться хвосту
        except asyncio.CancelledError:
            pass
        finally:
            self.stop = True
            sender.cancel()
            receiver.cancel()
            await asyncio.gather(sender, receiver, return_exceptions=True)
            if self.phase == "active":
                await self.send({"type": "call_hangup", "to_id": self.peer_id, "call_id": self.call_id})
            self._print_stats()
            try:
                await self.ws.close()
            except Exception:
                pass

    async def _sender(self) -> None:
        """Один кадр (seq++) в одном call_audio-сообщении, rate кадров/с."""
        interval = 1.0 / max(1, self.args.rate)
        try:
            while not self.stop:
                t0 = time.monotonic()
                if self.phase == "active":
                    seq = self.sent
                    ok = await self.send({
                        "type": "call_audio",
                        "to_id": self.peer_id,
                        "call_id": self.call_id,
                        "seq": seq,
                        "audio": self._audio_payload(seq),
                    })
                    if ok:
                        self.sent += 1
                # самоподстройка под реальный темп
                dt = time.monotonic() - t0
                await asyncio.sleep(max(0.0, interval - dt))
        except asyncio.CancelledError:
            pass

    async def _receiver(self) -> None:
        try:
            while not self.stop:
                try:
                    msg = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=2))
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    print(f"[cli] receiver WS closed: {e!r}", flush=True)
                    self.phase = "ended"
                    self.finished_reason = "ws-closed"
                    return
                self._on_ws_message(msg)
        except asyncio.CancelledError:
            pass

    def _print_stats(self) -> None:
        dur = time.monotonic() - self.t0 if self.t0 else 0
        print("\n===== STATS =====", flush=True)
        print(f"  reason       : {self.finished_reason or self.phase}", flush=True)
        print(f"  duration     : {dur:.1f}s" if dur else "  duration     : 0s", flush=True)
        if dur:
            print(f"  sent frames  : {self.sent} ({self.sent/dur:.1f} fps)", flush=True)
            print(f"  recv frames  : {self.received} ({self.received/dur:.1f} fps)", flush=True)
            print(f"  balance      : {self.received - self.sent:+d}", flush=True)
        else:
            print(f"  sent frames  : {self.sent}", flush=True)
            print(f"  recv frames  : {self.received}", flush=True)
        print(f"  send errors  : {self.send_errors}", flush=True)
        t = self.arrivals
        if len(t) > 1:
            tail = t[-min(100, len(t)):]
            dt = tail[-1] - tail[0]
            print(f"  recv rate    : {len(tail)/dt:.1f} fps (last {len(tail)} frames)", flush=True)
            deltas = [t[i] - t[i - 1] for i in range(1, len(t))]
            print(
                f"  frame deltas : min={min(deltas)*1000:.0f} med={statistics.median(deltas)*1000:.0f} "
                f"max={max(deltas)*1000:.0f} ms (n={len(deltas)})",
                flush=True,
            )
        if self.rtts:
            print(f"  ping RTT     : min={min(self.rtts):.1f} med={statistics.median(self.rtts):.1f} "
                  f"max={max(self.rtts):.1f} ms (n={len(self.rtts)})", flush=True)
        print(f"  seq gaps     : {self.gaps} (max {self.max_gap})", flush=True)
        print(f"  reorders     : {self.reorders}", flush=True)
        print(f"  dups         : {self.dups}", flush=True)
        print("================", flush=True)


def main() -> None:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--url", default=DEFAULT_URL, help="база HTTP (по умолчанию прод)")
    common.add_argument("--token", default=os.environ.get("NEKOCHAT_TOKEN", ""), help="JWT (иначе --user/--pass)")
    common.add_argument("--user", default=os.environ.get("NEKOCHAT_USER", ""))
    common.add_argument("--password", default=os.environ.get("NEKOCHAT_PASS", ""))
    common.add_argument("--peer", type=int, default=None, help="id вызываемого (caller)")
    common.add_argument("--rate", type=int, default=DEFAULT_RATE, help="кадров/с")
    common.add_argument("--duration", type=float, default=0, help="авто-завершение через N сек (0=до hangup)")
    common.add_argument("--answer-ms", type=int, default=0, help="callee: задержка ответа, мс")
    common.add_argument("--wait", type=float, default=60, help="callee: сколько ждать входящий call, с")

    p = argparse.ArgumentParser(description="Headless WS-клиент для диагностики звонков Nekochat")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp_login = sub.add_parser("login", parents=[common], help="логин и кеш токена")
    sp_caller = sub.add_parser("caller", parents=[common], help="позвонить --peer и гнать аудио")
    sp_callee = sub.add_parser("callee", parents=[common], help="принять входящий звонок и гнать аудио")
    sp_ping = sub.add_parser("ping", parents=[common], help="RTT по WS ping/pong")
    sp_ping.add_argument("--count", type=int, default=50, help="количество ping")
    sp_ping.add_argument("--ping-timeout", type=float, default=20, help="таймаут ожидания pong, с")
    sp_ping.add_argument("--ping-gap", type=float, default=0.5, help="пауза между ping, с")
    sp_nats = sub.add_parser("nats-ping", parents=[common], help="RTT по NATS (wss://…/nats)")
    sp_nats.add_argument("--count", type=int, default=50, help="количество ping")
    sp_nats.add_argument("--ping-timeout", type=float, default=20, help="таймаут ожидания pong, с")
    sp_nats.add_argument("--ping-gap", type=float, default=0.5, help="пауза между ping, с")
    args = p.parse_args()

    cli = Cli(args)
    try:
        if args.cmd == "login":
            cli.get_token()
            print(f"[cli] токен сохранён в {TOKEN_FILE}", flush=True)
        elif args.cmd == "caller":
            asyncio.run(cli.cmd_caller())
        elif args.cmd == "callee":
            asyncio.run(cli.cmd_callee())
        elif args.cmd == "ping":
            asyncio.run(cli.cmd_ping())
        elif args.cmd == "nats-ping":
            asyncio.run(cli.cmd_nats_ping())
    except KeyboardInterrupt:
        print("\n[cli] прервано", flush=True)
        sys.exit(130)


if __name__ == "__main__":
    main()