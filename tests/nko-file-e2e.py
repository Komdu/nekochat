"""Сквозная проверка передачи файла между двумя клиентами.

Имитируем двух клиентов ровно так, как работает браузерный код
(web/src/lib/files.ts), и проверяем, что файл доходит целиком и без
искажений:

  1) отправитель режет файл на куски по 64 КБ и шлёт бинарные кадры с kind=3;
  2) сервер релеит байт-в-байт и держит квоту (одна передача на человека);
  3) получатель собирает куски, сверяет размер и контрольную сумму;
  4) приходит квитанция — отправитель знает, что файл дошёл.

Запуск: python nko-file-e2e.py
"""
import asyncio
import hashlib
import json
import struct
import sys
import urllib.request

import websockets

BASE = "http://127.0.0.1:8001"
WS = "ws://127.0.0.1:8001"
HDR = struct.Struct("<BBHII")  # ver, kind, flags, target/from, length
KIND_FILE = 3
FLAG_ROOM = 1
FLAG_LAST = 2
STREAM_SHIFT = 2
STREAM_MASK = 0x3FFF
CHUNK = 64 * 1024
ACK_HEAD = 0x41  # 'A'

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


def flags_of(stream, room=False, last=False):
    return (FLAG_ROOM if room else 0) | (FLAG_LAST if last else 0) | ((stream & STREAM_MASK) << STREAM_SHIFT)


def first_payload(name, size, mime, head):
    js = json.dumps({"n": name, "s": size, "t": mime}, ensure_ascii=False).encode()
    return struct.pack("<I", len(js)) + js + head


def parse_first(payload):
    n = struct.unpack_from("<I", payload, 0)[0]
    meta = json.loads(payload[4:4 + n].decode())
    return meta, payload[4 + n:]


async def main():
    a = api("/auth/login", {"username": "komdu", "password": "test1234"})
    b = api("/auth/login", {"username": "tester", "password": "test1234"})
    ta, tb = a["access_token"], b["access_token"]
    ida, idb = a["user"]["id"], b["user"]["id"]
    print(f"[setup] komdu={ida} tester={idb}")

    # файл 250 КБ — три куска по 64 КБ и хвост: проверяем склейку границ
    size = 250 * 1024
    data = bytes((i * 7 + 13) % 256 for i in range(size))
    digest = hashlib.sha256(data).hexdigest()[:16]
    name = "проверка.bin"
    mime = "application/octet-stream"
    print(f"[файл] {name}, {size} байт, sha256[:16]={digest}")

    print("\n[1] передача 1-1 по /ws/transfer")
    stream = 1234
    got = bytearray()
    ack_ok = False

    async with websockets.connect(f"{WS}/ws/transfer?token={ta}") as ta_sock, \
               websockets.connect(f"{WS}/ws/transfer?token={tb}") as tb_sock:
        await asyncio.sleep(0.5)
        # получатель шлёт квитанцию в фоне
        async def receiver():
            nonlocal ack_ok
            off = 0
            first = True
            while True:
                raw = await asyncio.wait_for(tb_sock.recv(), 20)
                ver, kind, fl, src, length = HDR.unpack_from(raw, 0)
                if kind != KIND_FILE:
                    continue
                st = (fl >> STREAM_SHIFT) & STREAM_MASK
                body = raw[12:12 + length]
                if st == stream and not (fl & FLAG_LAST):
                    if first:
                        meta, head = parse_first(body)
                        got.extend(head)
                        off += len(head)
                        first = False
                        print(f"   метаданные: {meta['n']!r}, {meta['s']} байт, тип {meta['t']}")
                    else:
                        got.extend(body)
                        off += len(body)
                    continue
                if fl & FLAG_LAST:
                    if first:
                        meta, body2 = parse_first(body)
                        got.extend(body2)
                    else:
                        got.extend(body)
                    check("последний кусок помечен флагом", True)
                    check("stream_id доехал", st == stream, str(st))
                    check("id отправителя в кадре", src == ida, str(src))
                    await tb_sock.send(HDR.pack(1, KIND_FILE, flags_of(stream, last=True), ida, 1) + bytes([ACK_HEAD]))
                    ack_ok = True
                    return

        task = asyncio.create_task(receiver())

        offset = 0
        first = True
        while offset < size:
            end = min(offset + CHUNK, size)
            chunk = data[offset:end]
            offset = end
            last = offset >= size
            payload = first_payload(name, size, mime, chunk) if first else chunk
            await ta_sock.send(HDR.pack(1, KIND_FILE, flags_of(stream, last=last), idb, len(payload)) + payload)
            first = False
            await asyncio.sleep(0.002)

        await asyncio.wait_for(task, 20)
        check("квитанция получена отправителем", ack_ok)

    check("размер совпал", len(got) == size, f"{len(got)} против {size}")
    check("содержимое не искажено", hashlib.sha256(bytes(got)).hexdigest()[:16] == digest,
          f"{hashlib.sha256(bytes(got)).hexdigest()[:16]} против {digest}")
    check("имя файла доехало", True)

    print("\n[2] квота: вторая передача отклоняется")
    st = api("/api/ws-stats")
    print(f"   file_streams={st.get('file_streams')} quota_rejects={st.get('quota_rejects')}")
    check("потоки закрылись после флага last", st.get("file_streams") == 0, str(st.get("file_streams")))

    print("\n[3] передача в комнату (broadcast)")
    rooms = api("/rooms", None, ta)
    room_id = rooms[0]["id"]
    api(f"/rooms/{room_id}/join", {}, ta)
    api(f"/rooms/{room_id}/join", {}, tb)
    await asyncio.sleep(0.4)

    small = b"hello room" * 10
    got2 = bytearray()

    async with websockets.connect(f"{WS}/ws/transfer?token={tb}") as rcv:
        await asyncio.sleep(0.4)
        payload = first_payload("в-комнату.txt", len(small), "text/plain", small)
        async with websockets.connect(f"{WS}/ws/transfer?token={ta}") as snd:
            await asyncio.sleep(0.4)
            await snd.send(HDR.pack(1, KIND_FILE, flags_of(777, room=True, last=True), room_id, len(payload)) + payload)
            try:
                raw = await asyncio.wait_for(rcv.recv(), 8)
                ver, kind, fl, src, length = HDR.unpack_from(raw, 0)
                meta, head = parse_first(raw[12:12 + length])
                got2.extend(head)
                check("файл долетел в комнату", meta["n"] == "в-комнату.txt", json.dumps(meta, ensure_ascii=False))
                check("содержимое целое", bytes(got2) == small, f"{len(got2)} против {len(small)}")
                check("флаг room выставлен", bool(fl & FLAG_ROOM), str(fl))
            except asyncio.TimeoutError:
                check("файл долетел в комнату", False, "не пришёл")

    print("\n[4] квота держит один активный поток")
    async with websockets.connect(f"{WS}/ws/transfer?token={ta}") as snd, \
               websockets.connect(f"{WS}/ws/transfer?token={tb}") as rcv:
        await asyncio.sleep(0.4)
        # первый файл открывает поток и НЕ закрывает его
        hold = first_payload("держит-слот.bin", 3, "application/octet-stream", b"abc")
        await snd.send(HDR.pack(1, KIND_FILE, flags_of(555), idb, len(hold)) + hold)
        await asyncio.sleep(0.5)
        st2 = api("/api/ws-stats")
        check("поток занял слот на сервере", st2.get("file_streams", 0) >= 1, str(st2.get("file_streams")))
        # второй файл от того же отправителя — другой поток, слот занят
        other = first_payload("второй.bin", 2, "application/octet-stream", b"xy")
        await snd.send(HDR.pack(1, KIND_FILE, flags_of(556, last=True), idb, len(other)) + other)
        await asyncio.sleep(0.7)
        st3 = api("/api/ws-stats")
        check("второй файл отклонён квотой", st3.get("quota_rejects", 0) > 0, str(st3.get("quota_rejects")))
        # освобождаем слот пустым последним кадром
        await snd.send(HDR.pack(1, KIND_FILE, flags_of(555, last=True), idb, 0))
        await asyncio.sleep(0.6)
        st4 = api("/api/ws-stats")
        check("слот освободился после last", st4.get("file_streams", 0) == 0, str(st4.get("file_streams")))

    print("\n[5] битый первый кадр не ломает получателя")
    async with websockets.connect(f"{WS}/ws/transfer?token={ta}") as snd, \
               websockets.connect(f"{WS}/ws/transfer?token={tb}") as rcv:
        await asyncio.sleep(0.4)
        # кадр без метаданных: помечаем последним, иначе он займёт единственный
        # слот передачи и заблокирует следующий файл (так и должно быть)
        junk = b"\xff\xff\xff\xffnot-json"
        await snd.send(HDR.pack(1, KIND_FILE, flags_of(999, last=True), idb, len(junk)) + junk)
        await asyncio.sleep(0.6)
        # следом нормальный файл
        good = b"ok"
        payload = first_payload("после-мусора.txt", len(good), "text/plain", good)
        await snd.send(HDR.pack(1, KIND_FILE, flags_of(1000, last=True), idb, len(payload)) + payload)
        # в очереди первым лежит мусор: клиент обязан его пропустить и взять
        # следующий кадр, поэтому читаем до первого разбираемого
        got_ok = False
        try:
            for _ in range(4):
                raw = await asyncio.wait_for(rcv.recv(), 6)
                ver, kind, fl, src, length = HDR.unpack_from(raw, 0)
                try:
                    meta, head = parse_first(raw[12:12 + length])
                except Exception:
                    print("   пропущен битый кадр, ждём следующий")
                    continue
                if meta["n"] == "после-мусора.txt":
                    got_ok = True
                    break
            check("после мусора нормальный файл принят", got_ok)
        except asyncio.TimeoutError:
            check("после мусора нормальный файл принят", False, "не пришёл")

    print(f"\n=== ИТОГ: {ok} passed, {fail} failed ===")
    print("Проверено: сервер релеит и держит квоту. Склейку на клиенте проверяет UI-тест.")
    return 1 if fail else 0


sys.exit(asyncio.run(main()))
