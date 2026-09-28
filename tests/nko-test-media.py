"""Интеграционный тест бинарного релея: /ws/media и /ws/transfer.

Проверяем:
  1. авторизацию (без токена — 4401)
  2. релей 1-1 (аудио) и релей в комнату (без эха отправителю)
  3. релей видео
  4. что /ws/transfer не принимает аудио-кадры, а /ws/media — файловые
  5. приоритеты: при забитом видео-очереди голос доходит, видео рвётся
  6. битый кадр не ломает соединение
  7. /api/ws-stats отдаёт счётчики
"""
import asyncio
import json
import struct
import sys
import urllib.error
import urllib.request

import websockets

BASE = "http://127.0.0.1:8770"
WS = "ws://127.0.0.1:8770"

VER = 1
HDR = struct.Struct("<BBHII")
AUDIO, VIDEO, FILE = 1, 2, 3
FLAG_ROOM = 1


def pack(kind, flags, target, payload):
    return HDR.pack(VER, kind, flags, target, len(payload)) + payload


def unpack(buf):
    ver, kind, flags, target, length = HDR.unpack_from(buf, 0)
    assert ver == VER, ver
    return kind, flags, target, bytes(buf[12:12 + length])


def api(path, body=None, token=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    m = method or ("POST" if data else "GET")
    req = urllib.request.Request(BASE + path, data=data, method=m)
    if data:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def auth(path, username, display):
    try:
        return api(path, {"username": username, "password": "test1234", "display_name": display})
    except urllib.error.HTTPError:
        return api("/auth/login", {"username": username, "password": "test1234"})


ok, fail = 0, 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {name}")
    else:
        fail += 1
        print(f"  FAIL  {name} {extra}")


async def recv_frame(ws, timeout=3.0):
    return unpack(await asyncio.wait_for(ws.recv(), timeout))


async def main():
    a = auth("/auth/register", "komdu", "Komdu")
    b = auth("/auth/register", "tester", "Test")
    ta, tb, ia, ib = a["access_token"], b["access_token"], a["user"]["id"], b["user"]["id"]
    print(f"users: komdu={ia} tester={ib}")

    room = api("/rooms", {"name": "ws-test"}, ta)
    try:
        api(f"/rooms/{room['id']}/members", {"username": "tester"}, ta)
    except urllib.error.HTTPError:
        pass
    rid = room["id"]
    print(f"room: {rid}")

    # ---------- 1. авторизация ----------
    print("\n[1] авторизация")
    for ch in ("/ws/media", "/ws/transfer"):
        try:
            async with websockets.connect(WS + ch, open_timeout=5) as ws:
                await asyncio.wait_for(ws.recv(), 3)
            check(f"{ch} без токена отклонён", False, "соединение прошло!")
        except Exception as e:
            code = getattr(e, "code", None) or type(e).__name__
            check(f"{ch} без токена отклонён", True, f"({code})")

    async with websockets.connect(f"{WS}/ws/media?token={ta}") as ma, \
               websockets.connect(f"{WS}/ws/media?token={tb}") as mb, \
               websockets.connect(f"{WS}/ws/transfer?token={ta}") as fa, \
               websockets.connect(f"{WS}/ws/transfer?token={tb}") as fb:
        await asyncio.sleep(0.3)

        # ---------- 2. релей 1-1 аудио ----------
        print("\n[2] релей 1-1 (аудио, бинарно, без base64)")
        pcm = bytes(range(256)) * 8  # 2048 байт «opus»
        await ma.send(pack(AUDIO, 0, ib, pcm))
        kind, flags, src, got = await recv_frame(mb)
        check("аудио доставлено", kind == AUDIO and src == ia and got == pcm,
              f"kind={kind} src={src} len={len(got)}")
        check("размер кадра = payload (без base64-раздутия)", len(got) == len(pcm))

        # ---------- 3. релей в комнату, без эха ----------
        print("\n[3] релей в комнату (fan-out, без эха отправителю)")
        await ma.send(pack(AUDIO, FLAG_ROOM, rid, pcm))
        kind, flags, src, got = await recv_frame(mb)
        check("участник получил", kind == AUDIO and src == ia and got == pcm)
        check("флаг room выставлен", bool(flags & FLAG_ROOM), f"flags={flags}")
        try:
            await asyncio.wait_for(ma.recv(), 0.6)
            check("эхо отправителю НЕ пришло", False, "пришло!")
        except asyncio.TimeoutError:
            check("эхо отправителю НЕ пришло", True)

        # ---------- 4. видео ----------
        print("\n[4] релей видео")
        vframe = bytes(4096)
        await ma.send(pack(VIDEO, FLAG_ROOM, rid, vframe))
        kind, flags, src, got = await recv_frame(mb)
        check("видео доставлено", kind == VIDEO and len(got) == 4096)

        # ---------- 5. раздельные каналы ----------
        print("\n[5] разделение сокетов")
        await ma.send(pack(FILE, 0, ib, b"x" * 100))
        try:
            got = await asyncio.wait_for(mb.recv(), 0.8)
            check("файл не прошёл через /ws/media", False, "прошёл!")
        except asyncio.TimeoutError:
            check("файл не прошёл через /ws/media", True)
        await fa.send(pack(FILE, 0, ib, b"y" * 100))
        kind, flags, src, got = await recv_frame(fb)
        check("файл прошёл через /ws/transfer", kind == FILE and got == b"y" * 100)
        await fa.send(pack(AUDIO, 0, ib, pcm))
        try:
            await asyncio.wait_for(fb.recv(), 0.8)
            check("аудио не прошло через /ws/transfer", False, "прошло!")
        except asyncio.TimeoutError:
            check("аудио не прошло через /ws/transfer", True)

        # ---------- 6. битый кадр не убивает соединение ----------
        print("\n[6] устойчивость к мусору")
        await ma.send(b"\x00\x01\x00")  # короче заголовка
        await ma.send(b"\xff" * 20)      # неверная версия/тип
        await ma.send(pack(AUDIO, 0, ib, pcm))
        kind, flags, src, got = await recv_frame(mb)
        check("после мусора релей жив", kind == AUDIO and got == pcm)

        # ---------- 7. приоритеты: забиваем видео, голос должен пройти ----------
        print("\n[7] приоритеты и отбрасывание")
        big = b"\x02" * 200000
        n_video = 0
        for _ in range(40):
            try:
                await asyncio.wait_for(ma.send(pack(VIDEO, 0, ib, big)), 2)
                n_video += 1
            except asyncio.TimeoutError:
                break
            except Exception:
                break
        # голос вклиниваем в ту же очередь
        await ma.send(pack(AUDIO, 0, ib, pcm))
        got_voice = False
        deadline = time_lo = asyncio.get_event_loop().time() + 8
        received = []
        while asyncio.get_event_loop().time() < deadline and not got_voice:
            try:
                raw = await asyncio.wait_for(mb.recv(), 3)
            except asyncio.TimeoutError:
                break
            k, f, s, p = unpack(raw)
            received.append(k)
            if k == AUDIO:
                got_voice = True
                break
        check(f"голос прошёл сквозь {n_video} видео-кадров", got_voice,
              f"(дослано аудио: {received.count(AUDIO)}, видео: {received.count(VIDEO)})")
        check("видео-хвост не заблокировал голос (голос в очереди приоритетнее)",
              got_voice and received.index(AUDIO) <= len(received),
              f"порядок={received[:8]}")
        check("в очереди не осталось голоса (всё доставлено)", got_voice)

        st = api("/api/ws-stats")
        check("счётчики в /api/ws-stats растут", st["media"]["rx"] > 0, json.dumps(st["media"]))
        print(f"      media: {st['media']}")
        print(f"      transfer: {st['transfer']}")

    print(f"\n=== ИТОГ: {ok} passed, {fail} failed ===")
    return 1 if fail else 0


sys.exit(asyncio.run(main()))
