"""Квоты на файлы: 1 активная передача на пользователя, флаг last снимает её."""
import asyncio
import json
import struct
import sys
import urllib.error
import urllib.request

import websockets

sys.path.insert(0, r"D:\nekochat")
from app.config import settings
from app.ws_media import (  # noqa: E402
    FLAG_LAST,
    FLAG_ROOM,
    KIND_FILE,
    STREAM_MASK,
    pack_flags,
    unpack_flags,
)

BASE = "http://127.0.0.1:8770"
WS = "ws://127.0.0.1:8770"
HDR = struct.Struct("<BBHII")

ok, fail = 0, 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {name}")
    else:
        fail += 1
        print(f"  FAIL  {name} {extra}")


def pack(kind, flags, target, payload):
    return HDR.pack(1, kind, flags, target, len(payload)) + payload


def auth(user, display):
    try:
        return api("/auth/register", {"username": user, "password": "test1234", "display_name": display})
    except urllib.error.HTTPError:
        return api("/auth/login", {"username": user, "password": "test1234"})


def api(path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method="POST" if data else "GET")
    if data:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


async def drain(ws):
    """Сливает всё, что уже пришло — иначе сравниваем с хвостом предыдущего теста."""
    got = []
    while True:
        try:
            raw = await asyncio.wait_for(ws.recv(), 0.4)
        except asyncio.TimeoutError:
            return got
        ver, kind, flags, target, length = HDR.unpack_from(raw, 0)
        got.append((kind, flags, target, bytes(raw[12:12 + length])))


async def recv(ws, timeout=2.0):
    raw = await asyncio.wait_for(ws.recv(), timeout)
    ver, kind, flags, target, length = HDR.unpack_from(raw, 0)
    return kind, flags, target, bytes(raw[12:12 + length])


async def main():
    limit = settings.transfer_max_files_per_user
    print(f"квота из конфига: {limit} файл(а) на пользователя")

    a = auth("komdu", "Komdu")
    b = auth("tester", "Test")
    ta, tb, ib = a["access_token"], b["access_token"], b["user"]["id"]
    room = api("/rooms", {"name": "quota-test"}, ta)
    rid = room["id"]
    try:
        api(f"/rooms/{rid}/members", {"username": "tester"}, ta)
    except urllib.error.HTTPError:
        pass

    async with websockets.connect(f"{WS}/ws/transfer?token={ta}") as fa, \
               websockets.connect(f"{WS}/ws/transfer?token={tb}") as fb:
        await asyncio.sleep(0.3)

        print("\n[1] флаги: room/last/stream уживаются в одном поле")
        f = pack_flags(True, True, 1234)
        room_b, last_b, stream = unpack_flags(f)
        check("room+last+stream распакованы", room_b and last_b and stream == 1234, f"{room_b},{last_b},{stream}")
        check("stream в пределах 14 бит", 0 <= stream <= STREAM_MASK)
        check("обычный флаг 0 распаковывается в (False,False,0)", unpack_flags(0) == (False, False, 0))
        big = pack_flags(False, False, STREAM_MASK)
        check("максимальный stream не ломает room/last", unpack_flags(big) == (False, False, STREAM_MASK))

        print("\n[2] первый файл проходит")
        s1 = pack(KIND_FILE, pack_flags(False, False, 1), ib, b"A" * 500)
        await fa.send(s1)
        kind, flags, frm, got = await recv(fb)
        check("файл 1 доставлен", kind == KIND_FILE and got == b"A" * 500, f"kind={kind} len={len(got)}")

        print("\n[3] второй файл сверх квоты — отброшен")
        s2 = pack(KIND_FILE, pack_flags(False, False, 2), ib, b"B" * 500)
        await fa.send(s2)
        try:
            got = await recv(fb, 1.5)
            check("файл 2 НЕ доставлен", False, f"доставлен: {len(got[3])} байт")
        except asyncio.TimeoutError:
            check("файл 2 НЕ доставлен (квота)", True)

        print("\n[4] продолжение первого файла — проходит (тот же stream)")
        s1b = pack(KIND_FILE, pack_flags(False, False, 1), ib, b"A" * 500)
        await fa.send(s1b)
        kind, flags, frm, got = await recv(fb)
        check("продолжение файла 1 доставлено", got == b"A" * 500)

        print("\n[5] last снимает квоту -> можно начать новый файл")
        s1c = pack(KIND_FILE, pack_flags(False, True, 1), ib, b"A" * 100)
        await fa.send(s1c)
        kind, flags, frm, got = await recv(fb)
        check("финальный кадр доставлен и помечен last", bool(flags & FLAG_LAST))
        await asyncio.sleep(0.3)
        s3 = pack(KIND_FILE, pack_flags(False, False, 3), ib, b"C" * 500)
        await fa.send(s3)
        batch = await drain(fb)
        check("новый файл после last прошёл",
              any(p == b"C" * 500 for _, _, _, p in batch),
              f"получено {len(batch)} кадр(ов), длины {[len(p) for _, _, _, p in batch]}")

        print("\n[6] закрываем последний поток флагом last")
        s3b = pack(KIND_FILE, pack_flags(False, True, 3), ib, b"C" * 100)
        await fa.send(s3b)
        await asyncio.sleep(0.4)
        st_mid = api("/api/ws-stats")
        check("после last активных потоков нет", st_mid["file_streams"] == 0,
              f"streams={st_mid['file_streams']}")

        st = api("/api/ws-stats")
        print(f"      stats: {st}")
        check("quota_rejects учтён", st["quota_rejects"] >= 1, f"rejects={st['quota_rejects']}")
        check("активных потоков не осталось", st["file_streams"] == 0, f"streams={st['file_streams']}")

    print(f"\n=== ИТОГ: {ok} passed, {fail} failed ===")
    return 1 if fail else 0


sys.exit(asyncio.run(main()))
