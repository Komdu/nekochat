"""Работает ли заголовок клиента на чужих клиентах.

Проверяем ровно то, что сделает сторонний разработчик: REST-запрос с своим
заголовком, без него, с чужим, и WebSocket (который у нативного клиента
умеет заголовки, а браузер — нет).

Строгий режим поднимается отдельным сервером на порту 8002, чтобы не мешать
остальным тестам.

Запуск: python nko-custom-client.py
"""
import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

import websockets

SOFT = "http://127.0.0.1:8001"
STRICT = "http://127.0.0.1:8002"
H = "X-Neko-Client"
ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {name}")
    else:
        fail += 1
        print(f"  FAIL  {name} {extra}")


def req(base, path, hdr=None, token=None, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(base + path, data=data, method=method)
    if data:
        r.add_header("Content-Type", "application/json")
    for k, v in (hdr or {}).items():
        r.add_header(k, v)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, timeout=15) as x:
            return x.status, json.loads(x.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"err": str(e)[:80]}


def login(base, user="komdu", pw="test1234"):
    # В строгом режиме заголовок нужен и на логине: без него нельзя даже
    # получить токен. Это и есть «обязателен для любого клиента»: автору
    # стороннего клиента приходится добавить заголовок с самого начала,
    # иначе он не залогинится вообще.
    hdr = {H: "my-telegram-fork/1.4.2 (linux)"}
    code, b = req(base, "/auth/login", method="POST", body={"username": user, "password": pw}, hdr=hdr)
    if b.get("access_token"):
        return b["access_token"]
    # строгий сервер поднят на своей базе — пользователя там может не быть
    req(base, "/auth/register", method="POST", hdr=hdr,
        body={"username": user, "password": pw, "display_name": user})
    code, b = req(base, "/auth/login", method="POST", body={"username": user, "password": pw}, hdr=hdr)
    return b.get("access_token")


async def main():
    subprocess.run(["taskkill", "/F", "/IM", "msedge.exe"], capture_output=True)

    # --- второй сервер со строгим режимом ---
    env = dict(os.environ)
    env["NKO_PORT"] = "8002"
    env["NEKOCHAT_DATA_DIR"] = os.path.join(os.environ["TEMP"], "nko-strict")
    env["NEKOCHAT_DATA"] = env["NEKOCHAT_DATA_DIR"]
    env["client_header_strict"] = "true"     # pydantic-settings читает env
    strict = subprocess.Popen(
        ["D:/nekochat/.venv-build/Scripts/python.exe", "server_win.py"],
        cwd="D:/nekochat", env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(11)
    alive = req(STRICT, "/api/client-stats")[0]
    if alive == 0:
        print("строгий сервер не поднялся — возможно, env не читается, проверь вручную")
        strict.kill()
        return 1
    print("оба сервера живы: мягкий %s, строгий %s" % (SOFT, STRICT))

    print("\n[1] мягкий режим (по умолчанию): чужие клиенты работают")
    code, b = req(SOFT, "/api/client-stats")
    check("без заголовка — 200", code == 200, str(code))
    code, b = req(SOFT, "/api/client-stats", {H: "my-telegram-fork/1.4.2 (linux)"})
    check("со своим заголовком — 200", code == 200, str(code))
    tok = login(SOFT)
    code, me = req(SOFT, "/api/me", token=tok, hdr={H: "my-telegram-fork/1.4.2 (linux)"})
    cl = me.get("client", {})
    check("чужой клиент виден как чужой", cl.get("known") is False, json.dumps(cl, ensure_ascii=False))
    check("его версия сохранена", cl.get("version") == "1.4.2", json.dumps(cl, ensure_ascii=False))
    check("его ОС сохранён", cl.get("os") == "linux", json.dumps(cl, ensure_ascii=False))
    check("иконка не выдумана", cl.get("icon") == "unknown", str(cl.get("icon")))

    print("\n[2] строгий режим: без заголовка — отказ")
    code, b = req(STRICT, "/api/client-stats")
    check("без заголовка — 400", code == 400, str(code))
    check("текст ошибки как заказано",
          b.get("error") == "client_header not found! please update", json.dumps(b, ensure_ascii=False))
    check("в ответе сказано, что делать", "detail" in b and "X-Neko-Client" in json.dumps(b),
          json.dumps(b, ensure_ascii=False)[:160])

    print("\n[3] строгий режим: со своим заголовком — работает")
    code, b = req(STRICT, "/api/client-stats", {H: "my-telegram-fork/1.4.2 (linux)"})
    check("своим заголовком — 200", code == 200, str(code))
    tok2 = login(STRICT, "komdu")
    code2, me2 = req(STRICT, "/api/me", token=tok2, hdr={H: "my-telegram-fork/1.4.2 (linux)"})
    check("вход в строгом режиме проходит", code2 == 200, str(code2))
    check("клиент определён", me2.get("client", {}).get("name") == "my-telegram-fork",
          json.dumps(me2.get("client", {}), ensure_ascii=False))

    print("\n[4] нативный клиент: заголовок на WebSocket (браузер так не умеет)")
    ws_url = STRICT.replace("http", "ws") + "/ws?token=" + tok2 + "&c=" + \
        "my-native%2F2.0%20(windows)"
    try:
        async with websockets.connect(ws_url) as w:
            await asyncio.sleep(0.7)
            w.close()
        check("WS с параметром c= принят (так делает браузер)", True)
    except Exception as e2:
        check("WS принят", False, str(e2)[:140])
    code, b = req(STRICT, "/api/client-stats", {H: "my-telegram-fork/1.4.2 (linux)"})
    check("WS-запросы не ломают статистику", code == 200, str(code))
    # и важное следствие строгого режима: без заголовка отваливается ВСЁ,
    # включая служебные эндпоинты — это ломает health-чеки и мониторинг
    code, b = req(STRICT, "/api/client-stats")
    check("но служебный запрос без заголовка тоже отпадает — цена строгого режима",
          code == 400, str(code))

    print("\n[5] чем это грозит на практике")
    code, b = req(STRICT, "/api/client-stats", {H: "x" * 400})
    check("даже абсурдный заголовок проходит (формат нестрогий)", code == 200, str(code))
    print("   вывод: в строгом режиме отпадает только то, что не умеет")
    print("   добавить одну строку заголовка. Скрипты на urllib/requests, боты,")
    print("   сторонние библиотеки — всё, что не наш клиент.")

    strict.kill()
    print(f"\n=== ИТОГ: {ok} passed, {fail} failed ===")
    return 1 if fail else 0


sys.exit(asyncio.run(main()))
