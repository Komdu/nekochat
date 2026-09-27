"""Проверка интеграции Material Web Components через CDP.

Клиент должен быть запущен с --debug (CDP на 127.0.0.1:9222).

    python scripts/md_check.py

Что проверяется:
  1. в material-теме кнопки/поля заменены на <md-*>;
  2. value читается/пишется как у нативных элементов;
  3. подписи (label) уехали в поля и переводятся через data-t;
  4. type=password сохранён;
  5. реальный сценарий: регистрация кликом по md-кнопке -> токен;
  6. win98-тема: md-элементов нет.
"""
import asyncio
import json
import random
import urllib.request

import websockets


def page_ws_url():
    with urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=5) as r:
        pages = [t for t in json.loads(r.read()) if t.get("type") == "page"]
    return pages[0]["webSocketDebuggerUrl"] if pages else None


class CDP:
    def __init__(self, ws):
        self.ws = ws
        self._id = 0

    async def eval(self, expr):
        self._id += 1
        await self.ws.send(json.dumps({
            "id": self._id, "method": "Runtime.evaluate",
            "params": {"expression": expr, "returnByValue": True, "awaitPromise": True},
        }))
        while True:
            msg = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=15))
            if msg.get("id") == self._id:
                res = msg["result"]["result"]
                if msg["result"].get("exceptionDetails"):
                    return {"error": msg["result"]["exceptionDetails"].get("text", "exception")}
                return res.get("value")


async def main():
    url = page_ws_url()
    if not url:
        print("CDP-NOT-READY")
        return
    async with websockets.connect(url, open_timeout=10) as ws:
        c = CDP(ws)

        # --- 1. material-тема, перезагрузка ---
        await c.eval("localStorage.setItem('nk_theme','material-light'); 'ok'")
        await c.eval("location.reload(); 'reloading'")
        await asyncio.sleep(2.5)

        tags = await c.eval("""JSON.stringify({
          authBtn: (document.querySelector('#auth-button')||{}).tagName,
          userField: (document.querySelector('#auth-username')||{}).tagName,
          passField: (document.querySelector('#auth-password')||{}).tagName,
          msgField: (document.querySelector('#msg-input')||{}).tagName,
          sendBtn: (document.querySelector('#send-btn')||{}).tagName,
          passType: (document.querySelector('#auth-password')||{}).type,
          userLabel: (document.querySelector('#auth-username')||{}).label,
          nativeLeft: document.querySelectorAll('button:not([id])').length
        })""")
        print("tags:", tags)

        val = await c.eval("""(() => {
          const f = document.querySelector('#auth-username');
          f.value = 'probe_' + 42;
          const r = f.value;
          f.value = '';
          return r;
        })()""")
        print("value rw:", val)

        # --- 2. скрытые нативные подписи ---
        lbl = await c.eval("""JSON.stringify({
          hidden: getComputedStyle(document.querySelector('label[for=auth-username]')).display,
          dataMd: document.querySelector('label[for=auth-username]').dataset.md
        })""")
        print("labels:", lbl)

        # --- 3. end-to-end: регистрация кликом по md-кнопке ---
        user = "mdtest" + str(random.randint(100, 999))
        await c.eval(f"""(() => {{
          document.querySelector('#auth-switch-link a').click();  // вкладка "Регистрация"
          const set = (id, v) => {{ const el = document.querySelector(id); el.value = v; }};
          set('#auth-username', '{user}');
          set('#auth-password', 'pass1234');
          set('#auth-display', 'MD Tester');
          return 'filled';
        }})()""")
        await asyncio.sleep(0.3)
        await c.eval("document.querySelector('#auth-button').click(); 'clicked'")
        await asyncio.sleep(2.5)
        e2e = await c.eval("""JSON.stringify({
          token: !!localStorage.getItem('nk_token'),
          appShown: getComputedStyle(document.querySelector('#app')).display !== 'none'
        })""")
        print("e2e register:", user, e2e)

        # --- 4. win98: md не должно быть ---
        await c.eval("localStorage.removeItem('nk_token'); localStorage.setItem('nk_theme','win98-light'); location.reload(); 'r'")
        await asyncio.sleep(2.5)
        win = await c.eval("""JSON.stringify({
          theme: document.documentElement.dataset.theme,
          mdCount: document.querySelectorAll('md-filled-button, md-outlined-text-field').length,
          nativeBtn: (document.querySelector('#auth-button')||{}).tagName
        })""")
        print("win98:", win)
        print("MD-CHECK-DONE")


asyncio.run(main())
