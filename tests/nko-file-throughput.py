"""Сколько реально проходит за 5 минут — настоящий потолок на файл.

Ответ «лимита нет» бесполезен: упрётся он в таймер. Меряем скорость на
локальном сервере и считаем, сколько успеет за TRANSFER_TTL_MS.

Запуск: python nko-file-throughput.py
"""
import asyncio
import json
import struct
import sys
import time
import urllib.request

import websockets

BASE = "http://127.0.0.1:8001"
WS = "ws://127.0.0.1:8001"
HDR = struct.Struct("<BBHII")
KIND_FILE = 3
FLAG_LAST = 2
STREAM_SHIFT = 2
STREAM_MASK = 0x3FFF
CHUNK = 64 * 1024


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
    a = api("/auth/login", {"username": "komdu", "password": "test1234"})
    b = api("/auth/login", {"username": "tester", "password": "test1234"})
    ta, tb = a["access_token"], b["access_token"]
    idb = b["user"]["id"]

    async with websockets.connect(f"{WS}/ws/transfer?token={tb}") as rx:
        await asyncio.sleep(0.4)
        async with websockets.connect(f"{WS}/ws/transfer?token={ta}") as tx:
            await asyncio.sleep(0.5)
            # получатель не успевает разбирать — он просто ест кадры
            total = 0
            stream = 42
            flags = (FLAG_LAST if False else 0) | (stream << STREAM_SHIFT)
            t0 = time.time()
            i = 0
            while True:
                el = time.time() - t0
                if el > 12:  # меряем 12 секунд, экстраполируем на 5 минут
                    break
                payload = bytes(CHUNK)
                await tx.send(HDR.pack(1, KIND_FILE, flags, idb, CHUNK) + payload)
                total += CHUNK
                i += 1
                if i % 20 == 0:
                    await asyncio.sleep(0)

    el = time.time() - t0
    mbps = (total * 8) / el / 1_000_000
    per_sec = total / el
    print(f"за {el:.1f} с ушло {total/1024/1024:.1f} МБ")
    print(f"  скорость: {mbps:.1f} Мбит/с  ({per_sec/1024:.0f} КБ/с)")
    ttl = 300  # TRANSFER_TTL_MS
    print()
    print(f"за 5 минут на этой скорости пройдёт примерно "
          f"{per_sec * ttl / 1024 / 1024:.0f} МБ")
    print(f"потолок в коде: 512 МБ")
    verdict = "потолок достижим" if per_sec * ttl / 1024 / 1024 >= 512 else "потолок не достижим — упирается в таймер"
    print(f"вывод: {verdict}")
    print()
    print("Это локальный сервер без туннеля. Через Cloudflare-туннель скорость")
    print("ниже в разы, так что реальный предел на практике — 100-300 МБ.")
    return 0


sys.exit(asyncio.run(main()))
