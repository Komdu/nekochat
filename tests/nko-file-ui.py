"""Передача файла между ДВУМЯ браузерами — как два разных человека.

localStorage общий на все вкладки одного origins, поэтому две вкладки в одном
профиле — это один и тот же пользователь. Здесь запускаются два отдельных
процесса Edge со своими профилями и своими отладочными портами.

Проверяется то, чего не покрывают остальные тесты: настоящий File, настоящий
Blob и сборка файла из кусков на стороне получателя, включая границы кусков.

Запуск: python nko-file-ui.py [url]
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
PROF_A = r"C:\Users\Komdu\AppData\Local\Temp\nko-edge-fa"
PROF_B = r"C:\Users\Komdu\AppData\Local\Temp\nko-edge-fb"
PORT_A = 9343
PORT_B = 9344
URL = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5173/web_next/").rstrip("/") + "/"
SIZE = 300 * 1024   # 5 кусков по 64 КБ: проверяем склейку через границы

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
})(window.__T_USER)"""

SEND = """(async (n) => {
  const store = window.__nkoStore;
  const item = store.list.find(x => x.kind === 'dm');
  if (!item) return { err: 'нет личных чатов' };
  store.selectUser(item.user);
  await new Promise(r => setTimeout(r, 1200));
  const buf = new Uint8Array(n);
  for (let i = 0; i < n; i++) buf[i] = (i * 31 + 7) % 256;
  const file = new File([buf], 'двухоконный.bin', { type: 'application/octet-stream' });
  await store.sendFile(file);
  await new Promise(r => setTimeout(r, 3500));
  const t = store.transfers.find(x => x.dir === 'out');
  return t ? { name: t.name, state: t.state, err: t.error || '', prog: t.progress } : { err: 'нет записи' };
})(window.__T_SIZE)"""

RECV = """(async () => {
  await new Promise(r => setTimeout(r, 1500));
  const store = window.__nkoStore;
  const t = store.transfers.find(x => x.dir === 'in');
  if (!t) return { err: 'нет входящих' };
  if (!t.url) return { name: t.name, size: t.size, state: t.state, hasUrl: false };
  const blob = await (await fetch(t.url)).blob();
  const buf = new Uint8Array(await blob.arrayBuffer());
  let h = 2166136261;
  for (let i = 0; i < buf.length; i++) { h ^= buf[i]; h = Math.imul(h, 16777619) >>> 0; }
  return { name: t.name, size: t.size, state: t.state, hasUrl: true,
           len: buf.length, hash: h,
           hasBtn: !!document.querySelector('.file-dl'),
           hasPanel: !!document.querySelector('.files-panel') };
})()"""

# та же контрольная сумма, что считает отправитель
WANT = 2166136261
for i in range(SIZE):
    WANT ^= (i * 31 + 7) % 256
    WANT = (WANT * 16777619) & 0xFFFFFFFF


async def main():
    subprocess.run(["taskkill", "/F", "/IM", "msedge.exe"], capture_output=True)
    await asyncio.sleep(1)
    pa = launch(PORT_A, PROF_A)
    pb = launch(PORT_B, PROF_B)

    wa_url, wb_url = None, None
    for _ in range(40):
        wa_url = await page_ws(PORT_A)
        wb_url = await page_ws(PORT_B)
        if wa_url and wb_url:
            break
    if not (wa_url and wb_url):
        print("CDP не поднялся")
        pa.kill(); pb.kill()
        return 1

    print(f"[план] файл {SIZE} байт, два браузера: komdu и tester")
    async with websockets.connect(wa_url, max_size=64 * 1024 * 1024) as wa, \
               websockets.connect(wb_url, max_size=64 * 1024 * 1024) as wb:
        a = CDP(wa)
        b = CDP(wb)
        for c in (a, b):
            await c.send("Page.enable")
            await c.send("Runtime.enable")
        await a.send("Page.navigate", url=URL)
        await b.send("Page.navigate", url=URL)
        await asyncio.sleep(5)

        print("\n[1] вход разными людьми")
        await a.eval("window.__T_USER = 'komdu'; true")
        await a.eval(LOGIN)
        await asyncio.sleep(4)
        await b.eval("window.__T_USER = 'tester'; true")
        await b.eval(LOGIN)
        await asyncio.sleep(4)
        u1 = await a.eval("JSON.parse(localStorage.getItem('nk.user')||'{}').username")
        u2 = await b.eval("JSON.parse(localStorage.getItem('nk.user')||'{}').username")
        print("   браузер A: %s, браузер B: %s" % (u1, u2))
        check("вошли разными людьми", u1 == "komdu" and u2 == "tester", "%s / %s" % (u1, u2))

        print("\n[2] отправляем файл")
        await a.eval("window.__T_SIZE = %d; true" % SIZE)
        res = await a.eval(SEND)
        print("   " + json.dumps(res, ensure_ascii=False))
        check("отправка завершена", res.get("state") == "done", str(res))
        check("ошибки нет", not res.get("err"), str(res.get("err")))

        print("\n[3] получатель собрал файл из кусков")
        got = await b.eval(RECV)
        print("   " + json.dumps(got, ensure_ascii=False))
        check("входящий файл появился", "err" not in got, str(got.get("err")))
        check("имя совпало", got.get("name") == "двухоконный.bin", str(got.get("name")))
        check("размер совпал", got.get("size") == SIZE, "%s против %s" % (got.get("size"), SIZE))
        check("состояние done", got.get("state") == "done", str(got.get("state")))
        check("длина блоба совпала", got.get("len") == SIZE, str(got.get("len")))
        check("контрольная сумма совпала", got.get("hash") == WANT,
              "%s против %s" % (got.get("hash"), WANT))
        check("кнопка «Сохранить» есть", bool(got.get("hasBtn")))
        check("панель передач видна", bool(got.get("hasPanel")))

    pa.kill()
    pb.kill()
    print("\n=== ИТОГ: %d passed, %d failed ===" % (ok, fail))
    return 1 if fail else 0


sys.exit(asyncio.run(main()))
