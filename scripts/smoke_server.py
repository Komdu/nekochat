"""Быстрый smoke-тест Nekochat-сервера.

    python scripts/smoke_server.py [BASE_URL]

Проверяет: лендинг `/`, веб-UI `/web/`, /api/server-info, /api/health, CORS,
регистрацию, login, /api/me и WebSocket /ws.
"""
import asyncio
import json
import random
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"


def call(path, data=None, tok=None, raw=False, extra_headers=None):
    headers = {"Content-Type": "application/json"}
    if tok:
        headers["Authorization"] = "Bearer " + tok
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers=headers,
        method="POST" if data is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        body = r.read()
        if raw:
            return body, dict(r.headers)
        return json.loads(body)


async def ws_test(tok):
    import websockets

    u = urllib.parse.urlparse(BASE)
    ws_url = f"{'wss' if u.scheme == 'https' else 'ws'}://{u.netloc}/ws?token={tok}"
    async with websockets.connect(ws_url, open_timeout=10) as ws:
        await asyncio.wait_for(ws.recv(), timeout=5)  # первый кадр = status-broadcast
        return True


async def main():
    info = call("/api/server-info")
    health = call("/api/health")
    assert health.get("ok") is True and info.get("version")
    assert info["sqlite"] is True or "sqlite" in info

    landing, _ = call("/", raw=True)
    assert b"nekochat" in landing.lower() and "Скачать".encode() in landing
    web, _ = call("/web/", raw=True)
    assert b'id="auth"' in web and b"vendor/md.js" in web

    # CORS на защищённом роуте (браузер-кастомный клиент шлёт Origin; 401 тоже должен
    # нести CORS-заголовок — им падают и авторизационные ошибки)
    try:
        _, h = call("/api/me", raw=True, extra_headers={"Origin": "http://example.com"})
        raise AssertionError("ожидался 401 без токена")
    except urllib.error.HTTPError as e:
        assert e.code == 401
        h = dict(e.headers)
    # urllib нормализует имена заголовков в нижний регистр
    assert h.get("access-control-allow-origin") == "*"

    user = "smoke" + str(random.randint(1000, 9999))
    reg = call("/auth/register", {"username": user, "password": "pass1234", "display_name": "Smoke"})
    tok = reg["access_token"]
    me = call("/api/me", tok=tok)
    again = call("/auth/login", {"username": user, "password": "pass1234"})
    ws_ok = await ws_test(tok)
    assert me["username"] == user and again["access_token"] and ws_ok
    print(f"SMOKE-OK server={info['name']} v={info['version']} sqlite={info['sqlite']} "
          f"user={me['username']} ws={ws_ok}")


asyncio.run(main())
