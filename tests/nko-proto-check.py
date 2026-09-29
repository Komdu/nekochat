"""Что именно не так с геттером transferReady — смотрим прототип в браузере."""
import asyncio
import json
import shutil
import subprocess
import sys
import time
import urllib.request

import websockets

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 9342
PROF = r"C:\Users\Komdu\AppData\Local\Temp\nko-edge-proto"


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

    async def eval(self, expr):
        r = await self.send("Runtime.evaluate", expression=expr, awaitPromise=True,
                            returnByValue=True)
        if r.get("exceptionDetails"):
            ex = r["exceptionDetails"].get("exception", {})
            raise RuntimeError(str(ex.get("description", "?"))[:300])
        return r.get("result", {}).get("value")


PROBE = r"""
(() => {
  const api = window.__nkoApi;
  if (!api) return { err: 'нет __nkoApi' };
  const proto = Object.getPrototypeOf(api);
  const names = Object.getOwnPropertyNames(proto);
  const desc = Object.getOwnPropertyDescriptor(proto, 'transferReady');
  return {
    ctor: proto.constructor && proto.constructor.name,
    hasTransferReady: 'transferReady' in api,
    typeofTransferReady: typeof api.transferReady,
    value: api.transferReady,
    descKind: desc ? ('get' in desc ? 'getter' : typeof desc.value) : 'нет дескриптора',
    wsTransferOwn: Object.prototype.hasOwnProperty.call(api, 'wsTransfer'),
    wsTransferType: typeof api.wsTransfer,
    wsTransferState: api.wsTransfer ? api.wsTransfer.readyState : null,
    getters: names.filter(n => n.startsWith('get ') || n.includes('Ready')),
    allMembers: names.length,
  };
})()
"""


async def main():
    subprocess.run(["taskkill", "/F", "/IM", "msedge.exe"], capture_output=True)
    shutil.rmtree(PROF, ignore_errors=True)
    proc = subprocess.Popen(
        [EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
         "--no-default-browser-check", f"--remote-debugging-port={PORT}",
         f"--user-data-dir={PROF}", "--window-size=1000,700", "about:blank"],
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
        await cdp.send("Page.navigate", url="http://localhost:5173/web_next/")
        await asyncio.sleep(5)
        print(json.dumps(await cdp.eval(PROBE), ensure_ascii=False, indent=2))
    proc.kill()
    return 0


sys.exit(asyncio.run(main()))
