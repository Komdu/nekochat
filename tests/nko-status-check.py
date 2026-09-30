"""Живая рассылка статуса: меняем статус у одного клиента — видит ли второй.

Два браузера, как в nko-file-ui.py: разные профили, потому что две вкладки
одного origins делят localStorage и оказались бы одним человеком.

Запуск: python nko-status-check.py
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
PROF_A = r"C:\Users\Komdu\AppData\Local\Temp\nko-edge-sa"
PROF_B = r"C:\Users\Komdu\AppData\Local\Temp\nko-edge-sb"
PORT_A, PORT_B = 9345, 9346
URL = "http://localhost:5173/web_next/"
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
                    raise RuntimeError("%s: %s" % (method, msg["error"]))
                return msg.get("result", {})

    async def eval(self, expr):
        r = await self.send("Runtime.evaluate", expression=expr, awaitPromise=True,
                            returnByValue=True)
        if r.get("exceptionDetails"):
            ex = r["exceptionDetails"].get("exception", {})
            raise RuntimeError(str(ex.get("description", "?"))[:300])
        return r.get("result", {}).get("value")


def launch(port, profile):
    shutil.rmtree(profile, ignore_errors=True)
    return subprocess.Popen(
        [EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
         "--no-default-browser-check", "--remote-debugging-port=%d" % port,
         "--user-data-dir=" + profile, "--window-size=1100,800", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def page_ws(port):
    for _ in range(80):
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/json" % port, timeout=2) as r:
                for t in json.loads(r.read().decode()):
                    if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                        return t["webSocketDebuggerUrl"]
        except Exception:
            pass
        await asyncio.sleep(0.4)
    return None


LOGIN = """(async (u) => {
  const i = document.querySelectorAll('input');
  const set = (el, v) => {
    const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
    s.call(el, v); el.dispatchEvent(new Event('input', {bubbles:true}));
  };
  set(i[0], u); set(i[1], 'test1234');
  document.querySelector('form').requestSubmit();
  return true;
})(%s)"""

# статус виден в списке чатов у собеседника
STATUS_IN_LIST = """(async () => {
  await new Promise(r => setTimeout(r, 2000));
  const store = window.__nkoStore;
  const other = store.list.find(x => x.kind === 'dm');
  if (!other) return { err: 'нет личных чатов' };
  store.selectUser(other.user);
  await new Promise(r => setTimeout(r, 1500));
  const head = document.querySelector('.title-status');
  const sub = Array.from(document.querySelectorAll('.list-item .item-sub'))
    .map(e => e.textContent.trim());
  return {
    cached: (store.usersMap[other.id] || {}).status || '',
    inHeader: head ? head.textContent.trim() : '',
    inList: sub.filter(t => t.includes('играю')).length,
  };
})()"""


async def main():
    subprocess.run(["taskkill", "/F", "/IM", "msedge.exe"], capture_output=True)
    await asyncio.sleep(1)
    pa = launch(PORT_A, PROF_A)
    pb = launch(PORT_B, PROF_B)
    wa_url = wb_url = None
    for _ in range(40):
        wa_url = await page_ws(PORT_A)
        wb_url = await page_ws(PORT_B)
        if wa_url and wb_url:
            break
    if not (wa_url and wb_url):
        print("CDP не поднялся")
        pa.kill(); pb.kill()
        return 1

    async with websockets.connect(wa_url, max_size=64 * 1024 * 1024) as wa, \
               websockets.connect(wb_url, max_size=64 * 1024 * 1024) as wb:
        a, b = CDP(wa), CDP(wb)
        for c in (a, b):
            await c.send("Page.enable")
            await c.send("Runtime.enable")
        await a.send("Page.navigate", url=URL)
        await b.send("Page.navigate", url=URL)
        await asyncio.sleep(5)

        print("[1] вход разными людьми")
        await a.eval(LOGIN % "'komdu'")
        await asyncio.sleep(4)
        await b.eval(LOGIN % "'tester'")
        await asyncio.sleep(4)
        u1 = await a.eval("JSON.parse(localStorage.getItem('nk.user')||'{}').username")
        u2 = await b.eval("JSON.parse(localStorage.getItem('nk.user')||'{}').username")
        check("вошли разными людьми", u1 == "komdu" and u2 == "tester", "%s / %s" % (u1, u2))

        print("\n[2] komdu ставит статус «играю в X»")
        await a.eval("""(async () => {
          await window.__nkoStore.setMyStatus('играю в X');
          return true;
        })()""")
        await asyncio.sleep(1)
        own = await a.eval("JSON.parse(localStorage.getItem('nk.user')||{}).status")
        check("свой статус сохранён", own == "играю в X", str(own))

        print("\n[3] tester видит это без перезагрузки (через WebSocket)")
        res = await b.eval(STATUS_IN_LIST)
        print("   " + json.dumps(res, ensure_ascii=False))
        check("статус доехал в кэш собеседника", res.get("cached") == "играю в X", str(res.get("cached")))
        check("статус виден в шапке чата", res.get("inHeader") == "играю в X", str(res.get("inHeader")))
        check("статус виден в списке чатов", (res.get("inList") or 0) > 0, str(res.get("inList")))

        print("\n[4] очистка статуса")
        await a.eval("window.__nkoStore.setMyStatus('')")
        await asyncio.sleep(2)
        res2 = await b.eval("""(async () => {
          await new Promise(r => setTimeout(r, 1200));
          const store = window.__nkoStore;
          const ids = Object.keys(store.usersMap);
          for (const id of ids) {
            if (store.usersMap[id].status === '') delete store.usersMap[id].status;
          }
          return true;
        })()""")
        await asyncio.sleep(1)
        cleared = await b.eval("""(async () => {
          const store = window.__nkoStore;
          const other = store.list.find(x => x.kind === 'dm');
          await store.reload();
          await new Promise(r => setTimeout(r, 1200));
          return (store.usersMap[other.id] || {}).status || '';
        })()""")
        check("очищенный статус не возвращается", cleared in ("", None), repr(cleared))

    pa.kill(); pb.kill()
    print("\n=== ИТОГ: %d passed, %d failed ===" % (ok, fail))
    return 1 if fail else 0


sys.exit(asyncio.run(main()))
