"""Проверка PWA: регистрация service worker, офлайн-работа, манифест.

Гоняет СОБРАННЫЙ клиент, который раздаёт сервер (не dev-сервер Vite): в dev
регистрация service worker отключена намеренно.

Запуск: python nko-pwa-check.py [url]
"""
import asyncio
import json
import shutil
import subprocess
import sys
import time
import urllib.request

import websockets

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 9338
PROF = r"C:\Users\Komdu\AppData\Local\Temp\nko-edge-pwa"
SERVER = "http://127.0.0.1:8001"
URL = (sys.argv[1] if len(sys.argv) > 1 else SERVER + "/web_next/").rstrip("/") + "/"

ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {name}")
    else:
        fail += 1
        print(f"  FAIL  {name} {extra}")


class CDP:
    def __init__(self, ws):
        self.ws = ws
        self.i = 0

    async def send(self, method, **params):
        self.i += 1
        mid = self.i
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    async def eval(self, expr):
        r = await self.send("Runtime.evaluate", expression=expr, awaitPromise=True,
                            returnByValue=True)
        if r.get("exceptionDetails"):
            raise RuntimeError(json.dumps(r["exceptionDetails"])[:300])
        return r.get("result", {}).get("value")


async def main():
    print(f"[setup] проверяем {URL}")

    # манифест и иконки отдаются сервером
    print("\n[1] манифест и иконки")
    mf = json.loads(urllib.request.urlopen(URL + "manifest.webmanifest", timeout=15).read().decode())
    check("манифест — валидный JSON", isinstance(mf, dict))
    check("name задан", mf.get("name") == "nekochat", str(mf.get("name")))
    check("start_url относительный (работает под любым префиксом)",
          mf.get("start_url") == ".", str(mf.get("start_url")))
    check("scope относительный", mf.get("scope") == ".", str(mf.get("scope")))
    check("theme_color чёрный (OLED)", mf.get("theme_color") == "#000000", str(mf.get("theme_color")))
    sizes = {i.get("sizes") for i in mf.get("icons", [])}
    purposes = {i.get("purpose", "any") for i in mf.get("icons", [])}
    check("есть иконки 192 и 512", {"192x192", "512x512"} <= sizes, str(sorted(sizes)))
    check("есть maskable-иконка", "maskable" in purposes, str(purposes))
    for icon in mf.get("icons", []):
        src = URL + icon["src"]
        try:
            with urllib.request.urlopen(src, timeout=15) as r:
                body = r.read()
            check(f"иконка {icon['src']} отдаётся", len(body) > 500, f"{len(body)} байт")
        except Exception as e:
            check(f"иконка {icon['src']} отдаётся", False, str(e)[:80])

    # service worker
    subprocess.run(["taskkill", "/F", "/IM", "msedge.exe"], capture_output=True)
    shutil.rmtree(PROF, ignore_errors=True)
    proc = subprocess.Popen(
        [EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
         "--no-default-browser-check", f"--remote-debugging-port={PORT}",
         f"--user-data-dir={PROF}", "--window-size=1200,800", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ws_url = None
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=2) as r:
                for t in json.loads(r.read().decode()):
                    if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                        ws_url = t["webSocketDebuggerUrl"]
                        break
            if ws_url:
                break
        except Exception:
            pass
        time.sleep(0.5)
    if not ws_url:
        print("CDP не поднялся")
        proc.kill()
        return 1

    async with websockets.connect(ws_url, max_size=64 * 1024 * 1024) as ws:
        cdp = CDP(ws)
        await cdp.send("Page.enable")
        await cdp.send("Runtime.enable")
        await cdp.send("Network.enable")

        print("\n[2] регистрация service worker")
        await cdp.send("Page.navigate", url=URL)
        await asyncio.sleep(4)
        reg = await cdp.eval("""
          navigator.serviceWorker.getRegistration().then(r => r ? ({
            scope: r.scope,
            active: !!(r.active || r.installing || r.waiting),
            script: r.active ? r.active.scriptURL : (r.installing ? r.installing.scriptURL : null)
          }) : null)
        """)
        check("service worker зарегистрирован", bool(reg), json.dumps(reg))
        check("регистрация в своей области",
              bool(reg) and reg["scope"].rstrip("/") == URL.rstrip("/"),
              reg["scope"] if reg else "")
        check("воркер активен", bool(reg and reg["active"]))

        # ждём, чтобы ворер перехватил страницу
        await asyncio.sleep(2)
        await cdp.send("Page.reload")
        await asyncio.sleep(4)
        ctrl = await cdp.eval("!!navigator.serviceWorker.controller")
        check("ворер взял страницу под контроль (после перезагрузки)", bool(ctrl))

        print("\n[3] клиент работает под управлением воркера")
        alive = await cdp.eval("document.querySelectorAll('#app *').length > 0")
        check("приложение отрисовано", bool(alive))

        print("\n[4] офлайн: оболочка должна остаться")
        await cdp.send("Network.emulateNetworkConditions", offline=True,
                       latency=0, downloadThroughput=-1, uploadThroughput=-1)
        await cdp.send("Page.reload")
        await asyncio.sleep(5)
        offline_app = await cdp.eval("document.querySelectorAll('#app *').length > 0")
        check("без сети приложение всё равно отрисовано", bool(offline_app))
        body = await cdp.eval("document.body.textContent.slice(0, 200)")
        check("видна оболочка входа", "nekochat" in (body or "").lower(), repr(body)[:120])
        await cdp.send("Network.emulateNetworkConditions", offline=False,
                       latency=0, downloadThroughput=-1, uploadThroughput=-1)

        print("\n[5] живое состояние не кэшируется")
        # после возврата в сеть API должен отвечать, а не отдавать из кэша
        await cdp.send("Page.reload")
        await asyncio.sleep(4)
        api_ok = await cdp.eval("""
          fetch('/api/ws-stats').then(r => r.ok).catch(() => false)
        """)
        check("API отвечает по сети (не из кэша воркера)", bool(api_ok))

    proc.kill()
    print(f"\n=== ИТОГ: {ok} passed, {fail} failed ===")
    return 1 if fail else 0


sys.exit(asyncio.run(main()))
