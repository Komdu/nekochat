"""Проверка нового Svelte-клиента против живого локального сервера.

Браузера в этой сессии нет, поэтому проверяем то, что можно проверить без него:
  1. собранный клиент отдаётся и в нём есть авторизация
  2. REST/WS-эндпоинты, которыми пользуется клиент, живы
  3. бинарный медиа-сокет принимает кадры (транспорт уже перенесён)
  4. отправка сообщения комнате и получение её другим клиентом

Полноценный UI (вход, отрисовка) без браузера не проверить — это честно
отмечено в отчёте.
"""
import asyncio
import json
import re
import struct
import sys
import urllib.error
import urllib.request

import websockets

BASE = "http://127.0.0.1:8001"
WS = "ws://127.0.0.1:8001"
ok, fail = 0, 0


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


async def main():
    print("[1] собранный Svelte-клиент отдаётся сервером")
    with urllib.request.urlopen(BASE + "/web_next/", timeout=20) as r:
        html = r.read().decode()
    check("/web_next/ отдаётся", True)
    check("есть точка монтирования #app", 'id="app"' in html)
    check("подключён бандл из assets/", "/assets/index-" in html)
    check("тема ставится до отрисовки", "nk_theme" in html and "oled" in html)
    check("есть манифест PWA", "manifest.webmanifest" in html)

    # достаём имя бандла и качаем, чтобы убедиться, что он реальный
    m = re.search(r'src="(/[^"]*assets/index-[^"]+\.js)"', html)
    check("бандл найден в разметке", bool(m), html[:200] if not m else "")
    if m:
        with urllib.request.urlopen(BASE + m.group(1), timeout=20) as r:
            js = r.read().decode("utf-8", "replace")
        check("бандл непустой и содержит логику входа", len(js) > 20000 and "/auth/login" in js,
              f"size={len(js)}")

    print("\n[2] REST-эндпоинты клиента живы")
    a = api("/auth/login", {"username": "komdu", "password": "test1234"})
    b = api("/auth/login", {"username": "tester", "password": "test1234"})
    ta, tb = a["access_token"], b["access_token"]
    check("вход komdu", a["user"]["username"] == "komdu")
    check("вход tester", b["user"]["username"] == "tester")
    rooms = api("/rooms", None, ta)
    users = api("/users", None, ta)
    convs = api("/users/conversations/me", None, ta)
    check("GET /rooms", isinstance(rooms, list) and len(rooms) > 0, str(rooms)[:80])
    check("GET /users", isinstance(users, list))
    check("GET /users/conversations/me", isinstance(convs, list))

    print("\n[3] перенесённый бинарный медиа-транспорт работает")
    HDR = struct.Struct("<BBHII")

    def pack(kind, flags, target, payload):
        return HDR.pack(1, kind, flags, target, len(payload)) + payload

    async with websockets.connect(f"{WS}/ws/media?token={tb}") as mb, \
               websockets.connect(f"{WS}/ws/media?token={ta}") as ma:
        await asyncio.sleep(0.4)
        pcm = bytes(range(256)) * 4
        await ma.send(pack(1, 0, b["user"]["id"], pcm))
        raw = await asyncio.wait_for(mb.recv(), 5)
        ver, kind, flags, src, length = HDR.unpack_from(raw, 0)
        got = bytes(raw[12:12 + length])
        check("аудио-кадр доставлен через /ws/media", kind == 1 and got == pcm and src == a["user"]["id"],
              f"kind={kind} src={src} len={length}")

    st = api("/api/ws-stats")
    check("релей посчитал кадр (накопительный total_rx>0)", st["total_rx"] > 0, json.dumps(st))

    print("\n[4] сообщения комнаты (то, чем пользуется UI)")
    room_id = rooms[0]["id"]
    async with websockets.connect(f"{WS}/ws?token={tb}") as wsb:
        await asyncio.sleep(0.4)
        # вступаем в комнату (клиент делает это через POST, здесь — тем же REST)
        api(f"/rooms/{room_id}/join", {}, ta)
        ws_a = await websockets.connect(f"{WS}/ws?token={ta}")
        await asyncio.sleep(0.4)
        await ws_a.send(json.dumps({"type": "room_message", "room_id": room_id, "content": "проверка из скрипта"}))
        got_msg = None
        try:
            while True:
                raw = await asyncio.wait_for(wsb.recv(), 5)
                ev = json.loads(raw)
                if ev.get("type") == "room_message":
                    got_msg = ev
                    break
        except asyncio.TimeoutError:
            pass
        check("сообщение доставлено участнику", got_msg is not None and got_msg["message"]["content"] == "проверка из скрипта",
              json.dumps(got_msg)[:120] if got_msg else "не пришло")
        await ws_a.close()

    hist = api(f"/rooms/{room_id}/messages", None, ta)
    check("история комнаты доступна (её грузит openHistory)", isinstance(hist, list) and len(hist) > 0)

    print(f"\n=== ИТОГ: {ok} passed, {fail} failed ===")
    print("ВАЖНО: UI (вход, отрисовка списка и сообщений) без браузера не проверен.")
    return 1 if fail else 0


sys.exit(asyncio.run(main()))
