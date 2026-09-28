"""Снимок главного экрана в выбранной теме (без диалогов).

Запуск: python nko-chat-shot.py [oled|material|win98] [out.png]
"""
import asyncio
import base64
import json
import shutil
import subprocess
import sys
import time
import urllib.request

import websockets

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 9337
PROF = r"C:\Users\Komdu\AppData\Local\Temp\nko-edge-chat"
TMP = r"C:\Users\Komdu\AppData\Local\Temp"

THEME = sys.argv[1] if len(sys.argv) > 1 else "oled"
OUT = sys.argv[2] if len(sys.argv) > 2 else f"{TMP}\\nko-main-{THEME}.png"
MODE = "win98-dark" if THEME == "win98" else f"{THEME}-dark"
if THEME == "material":
    MODE = "material-light"  # у Material есть светлая сторона — покажем её


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
    subprocess.run(["taskkill", "/F", "/IM", "msedge.exe"], capture_output=True)
    shutil.rmtree(PROF, ignore_errors=True)
    proc = subprocess.Popen(
        [EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
         "--no-default-browser-check", f"--remote-debugging-port={PORT}",
         f"--user-data-dir={PROF}", "--window-size=1280,820", "about:blank"],
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
        # тету ставим до загрузки — так же, как это делает index.html
        await cdp.send("Page.addScriptToEvaluateOnNewDocument",
                       source=f"try{{localStorage.setItem('nk_theme','{MODE}')}}catch(e){{}}")
        await cdp.send("Page.navigate", url="http://localhost:5173/web_next/")
        await asyncio.sleep(4)
        await cdp.eval("""
          (() => {
            const i = document.querySelectorAll('input');
            const set = (el, v) => {
              const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
              s.call(el, v); el.dispatchEvent(new Event('input', {bubbles:true}));
            };
            set(i[0], 'komdu'); set(i[1], 'test1234');
            document.querySelector('form').requestSubmit();
            return true;
          })()
        """)
        await asyncio.sleep(4)
        cur = await cdp.eval("document.documentElement.dataset.theme + '/' + document.documentElement.dataset.mode")
        print(f"тема на экране: {cur}")
        r = await cdp.send("Page.captureScreenshot", format="png")
        with open(OUT, "wb") as f:
            f.write(base64.b64decode(r["data"]))
        print(f"-> {OUT}")
    proc.kill()
    return 0


sys.exit(asyncio.run(main()))
