"""Замеряем, что происходит с аватаром и кнопками в темах.

Запуск: python nko-measure.py
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
PORT = 9336
PROF = r"C:\Users\Komdu\AppData\Local\Temp\nko-edge-meas"


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


MEASURE = """
(() => {
  const av = document.querySelector('.me-row .avatar');
  if (!av) return { found: false };
  const r = av.getBoundingClientRect();
  const cs = getComputedStyle(av);
  const btn = document.querySelector('.dlg-foot .btn:not(.btn-ghost)');
  const bcs = btn ? getComputedStyle(btn) : null;
  const card = document.querySelector('.dlg-card');
  const ccs = getComputedStyle(card);
  return {
    found: true,
    theme: document.documentElement.dataset.theme,
    avatar: { w: Math.round(r.width), h: Math.round(r.height), x: Math.round(r.x),
              bg: cs.backgroundImage.slice(0, 70), radius: cs.borderRadius },
    btn: bcs ? { radius: bcs.borderRadius, border: bcs.borderWidth, bg: bcs.backgroundColor } : null,
    card: { radius: ccs.borderRadius, border: ccs.borderWidth, bg: ccs.backgroundColor },
  };
})()
"""


async def main():
    subprocess.run(["taskkill", "/F", "/IM", "msedge.exe"], capture_output=True)
    shutil.rmtree(PROF, ignore_errors=True)
    proc = subprocess.Popen(
        [EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
         "--no-default-browser-check", f"--remote-debugging-port={PORT}",
         f"--user-data-dir={PROF}", "--window-size=1100,860", "about:blank"],
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

        for label in ["OLED", "Win98", "Material You"]:
            await cdp.eval("""
              (() => {
                const b = Array.from(document.querySelectorAll('.side-foot button'))
                  .find(x => x.title === 'Настройки');
                if (b) b.click();
                return true;
              })()
            """)
            await asyncio.sleep(0.7)
            await cdp.eval("""
              (() => {
                const t = Array.from(document.querySelectorAll('.theme'))
                  .find(x => x.textContent.includes(%s));
                if (t) t.click();
                return true;
              })()
            """ % json.dumps(label))
            await asyncio.sleep(0.8)
            m = await cdp.eval(MEASURE)
            print(f"[{label}]")
            print("   аватар:", json.dumps(m.get("avatar", {}), ensure_ascii=False))
            print("   кнопка:", json.dumps(m.get("btn", {}), ensure_ascii=False))
            print("   карточка:", json.dumps(m.get("card", {}), ensure_ascii=False))
            await cdp.send("Input.dispatchKeyEvent", type="keyDown", key="Escape", code="Escape", windowsVirtualKeyCode=27)
            await cdp.send("Input.dispatchKeyEvent", type="keyUp", key="Escape", code="Escape", windowsVirtualKeyCode=27)
            await asyncio.sleep(0.5)
    proc.kill()
    return 0


sys.exit(asyncio.run(main()))
