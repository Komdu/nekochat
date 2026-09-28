"""Сквозная проверка звонка 1-1: сигналинг по /ws + аудио по /ws/media.

Имитирует двух клиентовnekochat (ровно то, что делает CallEngine из
web/src/lib/calls.ts) и проверяет, что сервер их соединяет: принял `call`,
доставил `call_answer`, и после этого бинарные Opus-кадры доходят от одного
к другому. Проверяется вся цепочка, кроме самого кодирования звука — это
делает браузер, его здесь нет.

Запуск: python nko-call-e2e.py
"""
import asyncio
import json
import struct
import sys
import urllib.request

import websockets

BASE = "http://127.0.0.1:8001"
WS = "ws://127.0.0.1:8001"
HDR = struct.Struct("<BBHII")  # ver, kind, flags, target/from, length
FLAG_ROOM = 1

ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {name}")
    else:
        fail += 1
        print(f"  FAIL  {name} {extra}")


def api(path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method="POST" if data else "GET")
    if data:
        r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(r, timeout=20) as x:
        return json.loads(x.read().decode())


async def recv_until(ws, want, timeout=6):
    """Читаем события, пока не найдём нужный тип. Возвращает его или None."""
    loop = asyncio.get_event_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        left = end - loop.time()
        try:
            raw = await asyncio.wait_for(ws.recv(), max(0.1, left))
        except asyncio.TimeoutError:
            return None
        try:
            ev = json.loads(raw)
        except Exception:
            continue
        if ev.get("type") == want:
            return ev
    return None


async def main():
    a = api("/auth/login", {"username": "komdu", "password": "test1234"})
    b = api("/auth/login", {"username": "tester", "password": "test1234"})
    ta, tb = a["access_token"], b["access_token"]
    ida, idb = a["user"]["id"], b["user"]["id"]
    print(f"[setup] komdu={ida} tester={idb}")

    print("\n[1] входящий звонок: A -> B")
    async with websockets.connect(f"{WS}/ws?token={ta}") as wa, \
               websockets.connect(f"{WS}/ws?token={tb}") as wb:
        await asyncio.sleep(0.4)
        await wa.send(json.dumps({"type": "call", "to_id": idb, "call_id": "call-e2e-1"}))
        ev = await recv_until(wb, "call")
        check("B получил call_invite", ev is not None and ev.get("from_id") == ida,
              json.dumps(ev)[:140] if ev else "не пришёл")
        check("call_id сохранён", bool(ev and ev.get("call_id")), json.dumps(ev)[:140] if ev else "")
        call_id = ev["call_id"] if ev else "call-e2e-1"

        print("\n[2] B принял звонок -> A ждёт call_answer")
        await wb.send(json.dumps({"type": "call_answer", "to_id": ida, "call_id": call_id}))
        ev2 = await recv_until(wa, "call_answer")
        check("A получил call_answer", ev2 is not None, json.dumps(ev2)[:140] if ev2 else "не пришёл")

    print("\n[3] аудио идёт по бинарному сокету во время звонка")
    async with websockets.connect(f"{WS}/ws/media?token={ta}") as ma, \
               websockets.connect(f"{WS}/ws/media?token={tb}") as mb:
        await asyncio.sleep(0.4)
        pcm = bytes(range(256)) * 8   # 2 КБ — размер 20мс фрейма Opus-пачки PCM-подобной нагрузки
        frame = HDR.pack(1, 1, 0, idb, len(pcm)) + pcm   # ver=1, kind=1 audio, flags=0, target=B
        got = None
        for _ in range(20):
            await ma.send(frame)
            try:
                raw = await asyncio.wait_for(mb.recv(), 2)
            except asyncio.TimeoutError:
                continue
            ver, kind, flags, src, length = HDR.unpack_from(raw, 0)
            got = (kind, flags, src, bytes(raw[12:12 + length]))
            break
        check("аудио-кадр A -> B доставлен",
              got is not None and got[0] == 1 and got[2] == ida and got[3] == pcm,
              str(got)[:120] if got else "ничего не пришло")
        check("в кадре id отправителя (не адресата)", bool(got) and got[2] != idb,
              f"from={got[2]}" if got else "")

        print("\n[4] голосовой канал: broadcast по комнате (флаг room)")
        rooms = api("/rooms", None, ta)
        room_id = rooms[0]["id"]
        api(f"/rooms/{room_id}/join", {}, ta)
        api(f"/rooms/{room_id}/join", {}, tb)
        await asyncio.sleep(0.3)
        rf = HDR.pack(1, 1, FLAG_ROOM, room_id, len(pcm)) + pcm
        got2 = None
        for _ in range(20):
            await ma.send(rf)
            try:
                raw = await asyncio.wait_for(mb.recv(), 2)
            except asyncio.TimeoutError:
                continue
            ver, kind, flags, src, length = HDR.unpack_from(raw, 0)
            got2 = (kind, flags, src)
            break
        check("кадр по комнате доставлен B с флагом room",
              got2 is not None and got2[1] & FLAG_ROOM and got2[0] == 1,
              str(got2) if got2 else "ничего не пришло")

    print("\n[5] завершение звонка")
    async with websockets.connect(f"{WS}/ws?token={ta}") as wa, \
               websockets.connect(f"{WS}/ws?token={tb}") as wb:
        await asyncio.sleep(0.4)
        await wa.send(json.dumps({"type": "call_hangup", "to_id": idb, "call_id": "call-e2e-1"}))
        ev3 = await recv_until(wb, "call_hangup")
        check("B получил call_hangup", ev3 is not None, json.dumps(ev3)[:140] if ev3 else "не пришёл")

    st = api("/api/ws-stats")
    print(f"\n  ws-stats: total_rx={st['total_rx']} total_tx={st['total_tx']} "
          f"total_dropped={st['total_dropped']}")
    check("релей посчитал кадры (total_rx>0)", st["total_rx"] > 0, json.dumps(st))

    print(f"\n=== ИТОГ: {ok} passed, {fail} failed ===")
    print("Проверено: сервер соединяет клиентов. Кодирование звука и сам UI — в браузере.")
    return 1 if fail else 0


sys.exit(asyncio.run(main()))
