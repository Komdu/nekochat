"""Диагностика канала передачи файлов прямо в браузере.

Заходит в клиент, смотрит состояние сокета /ws/transfer и пробует отправить
файл настоящим кодом клиента. Ничего не предполагает — показывает факт.

Запуск: python nko-file-debug.py [url]
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
PORT = 9341
PROF = r"C:\Users\Komdu\AppData\Local\Temp\nko-edge-fdbg"
URL = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5173/web_next/").rstrip("/") + "/"


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
                    raise RuntimeError("%s: %s" % (method, msg["error"]))
                return msg.get("result", {})

    async def eval(self, expr, note=""):
        r = await self.send("Runtime.evaluate", expression=expr, awaitPromise=True,
                            returnByValue=True)
        if r.get("exceptionDetails"):
            ex = r["exceptionDetails"].get("exception", {})
            raise RuntimeError("%s: %s" % (note, ex.get("description", "?")[:300]))
        return r.get("result", {}).get("value")


STATE = r"""
(() => {
  const api = window.__nkoApi;
  if (!api) return { err: 'нет dev-хука __nkoApi' };
  const t = api.wsTransfer, m = api.wsMedia;
  const name = { 0: 'CONNECTING', 1: 'OPEN', 2: 'CLOSING', 3: 'CLOSED' };
  return {
    token: !!api.token,
    transferReady: api.transferReady,
    transferState: t ? name[t.readyState] : 'нет сокета',
    transferUrl: t ? t.url.replace(/token=[^&]*/, 'token=...') : null,
    mediaState: m ? name[m.readyState] : 'нет сокета',
    mediaDesired: api.wsMediaDesired,
    base: api.base,
  };
})()
"""

SEND = r"""
(async () => {
  const store = window.__nkoStore;
  if (!store) return { err: 'нет стора' };
  const item = store.list.find(x => x.kind === 'dm');
  if (!item) return { err: 'нет личных чатов', list: store.list.length };
  store.selectUser(item.user);
  await new Promise(r => setTimeout(r, 1200));
  const file = new File([new Uint8Array(4096).fill(65)], 'proba.bin', { type: 'application/octet-stream' });
  await store.sendFile(file);
  await new Promise(r => setTimeout(r, 2500));
  return {
    transfers: store.transfers.map(t => ({
      dir: t.dir, name: t.name, state: t.state, err: t.error, prog: Math.round(t.progress),
    })),
  };
})()
"""


async def main():
    subprocess.run(["taskkill", "/F", "/IM", "msedge.exe"], capture_output=True)
    shutil.rmtree(PROF, ignore_errors=True)
    proc = subprocess.Popen(
        [EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
         "--no-default-browser-check", f"--remote-debugging-port={PORT}",
         f"--user-data-dir={PROF}", "--window-size=1100,800", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ws_url = None
    for _ in range(60):
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/json" % PORT, timeout=2) as r:
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
        await cdp.send("Page.navigate", url=URL)
        await asyncio.sleep(4)

        print("[до входа]")
        print(json.dumps(await cdp.eval(STATE), ensure_ascii=False, indent=2))

        print("\n[вход]")
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
        print("[после входа]")
        print(json.dumps(await cdp.eval(STATE), ensure_ascii=False, indent=2))

        print("\n[ждём 3 с]")
        await asyncio.sleep(3)
        print(json.dumps(await cdp.eval(STATE), ensure_ascii=False, indent=2))

        print("\n[пробуем отправить файл настоящим кодом]")
        print(json.dumps(await cdp.eval(SEND), ensure_ascii=False, indent=2))

        print("\n[состояние после попытки]")
        print(json.dumps(await cdp.eval(STATE), ensure_ascii=False, indent=2))

    proc.kill()
    return 0


sys.exit(asyncio.run(main()))
