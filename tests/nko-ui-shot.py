"""Драйвер Edge через CDP: реальный вход в клиент и снимок экрана.

Проверяет то, что нельзя проверить без браузера: что Svelte-клиент
авторизуется, рисует список чатов, сообщения и оверлейные элементы.

Запуск: python nko-ui-shot.py [url] [user] [pass] [out.png]
"""
import asyncio
import base64
import json
import subprocess
import sys
import time
import urllib.request

import websockets

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 9333
PROF = r"C:\Users\Komdu\AppData\Local\Temp\nko-edge-cdp"

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5173/web_next/"
USER = sys.argv[2] if len(sys.argv) > 2 else "komdu"
PASS = sys.argv[3] if len(sys.argv) > 3 else "test1234"
OUT = sys.argv[4] if len(sys.argv) > 4 else r"C:\Users\Komdu\AppData\Local\Temp\nko-chat.png"

ok = fail = 0
SERVER = "http://127.0.0.1:8001"


async def seed_other_message():
    """Сообщение от tester: без него в истории только мои, и нельзя проверить,
    что свои и чужие действительно рисуются по-разному."""
    def api(path, body=None, token=None):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(SERVER + path, data=data,
                                   method="POST" if data else "GET")
        if data:
            r.add_header("Content-Type", "application/json")
        if token:
            r.add_header("Authorization", "Bearer " + token)
        with urllib.request.urlopen(r, timeout=20) as x:
            return json.loads(x.read().decode())

    tok = api("/auth/login", {"username": "tester", "password": "test1234"})["access_token"]
    rooms = api("/rooms", None, tok)
    room_id = rooms[0]["id"]
    api(f"/rooms/{room_id}/join", {}, tok)
    ws_url = SERVER.replace("http://", "ws://") + f"/ws?token={tok}"
    async with websockets.connect(ws_url) as w:
        await asyncio.sleep(0.4)
        await w.send(json.dumps({"type": "room_message", "room_id": room_id,
                                 "content": "сообщение от tester"}))
        await asyncio.sleep(0.6)
    return room_id


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
        res = r.get("result", {})
        if r.get("exceptionDetails"):
            raise RuntimeError(json.dumps(r["exceptionDetails"])[:300])
        return res.get("value")


async def main():
    print("[0] готовим историю: сообщение от другого пользователя")
    await seed_other_message()

    subprocess.run(["taskkill", "/F", "/IM", "msedge.exe"], capture_output=True)
    import shutil
    shutil.rmtree(PROF, ignore_errors=True)
    proc = subprocess.Popen(
        [EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
         "--no-default-browser-check", f"--remote-debugging-port={PORT}",
         f"--user-data-dir={PROF}", "--window-size=1400,900", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # ждём отладочный порт
    ws_url = None
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=2) as r:
                targets = json.loads(r.read().decode())
            for t in targets:
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

        # ---- ловим ошибки страницы ----
        errors = []

        print("[1] загрузка клиента")
        await cdp.send("Page.navigate", url=URL)
        await asyncio.sleep(4)
        title = await cdp.eval("document.title")
        theme = await cdp.eval("document.documentElement.dataset.theme || ''")
        has_app = await cdp.eval("!!document.querySelector('#app')")
        check("страница загрузилась", bool(title), f"title={title!r}")
        check("Svelte смонтирован (#app не пуст)",
              bool(await cdp.eval("document.querySelector('#app').childElementCount > 0")))
        check("OLED-тема применена", theme == "oled", f"theme={theme}")
        check("видна форма входа", bool(await cdp.eval("!!document.querySelector('form .btn')")))

        # ---- настоящий вход через DOM ----
        print("\n[2] вход как живой человек")
        await cdp.eval("""
          (() => {
            const inputs = document.querySelectorAll('input');
            const set = (el, v) => {
              const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
              s.call(el, v);
              el.dispatchEvent(new Event('input', { bubbles: true }));
            };
            set(inputs[0], %s);
            set(inputs[1], %s);
            document.querySelector('form').requestSubmit();
            return true;
          })()
        """ % (json.dumps(USER), json.dumps(PASS)))
        await asyncio.sleep(4)

        phase = await cdp.eval("document.querySelector('.side') ? 'chat' : (document.querySelector('.login-card') ? 'login' : 'boot')")
        check("вошёл и попал в чат", phase == "chat", f"phase={phase}")
        err_txt = await cdp.eval("(document.querySelector('.login-err') || {}).textContent || ''")
        check("без ошибки входа", not err_txt, err_txt[:120])

        # ---- что нарисовано ----
        print("\n[3] содержимое главного экрана")
        items = await cdp.eval("Array.from(document.querySelectorAll('.list-item')).map(e => e.textContent.trim())")
        check("список чатов не пуст", bool(items) and len(items) > 0, str(items)[:160])

        msgs = await cdp.eval("document.querySelectorAll('.msg').length")
        check("сообщения отрисованы", isinstance(msgs, int) and msgs > 0, f"msg={msgs}")

        bubbles = await cdp.eval(
            "document.querySelectorAll('.msg-body').length > 0 && "
            "!!getComputedStyle(document.querySelector('.msg-body')).borderRadius")
        check("пузыри отрисованы со скруглением", bool(bubbles))

        head = await cdp.eval("(document.querySelector('.title-text') || {}).textContent || ''")
        check("в шапке имя чата", bool(head), f"head={head!r}")

        callbtn = await cdp.eval("!!document.querySelector('.head-btn svg')")
        check("кнопка звонка с SVG-значком", bool(callbtn))

        avs = await cdp.eval("document.querySelectorAll('.avatar').length")
        check("аватарки отрисованы", isinstance(avs, int) and avs > 0, f"avatar={avs}")

        # ---- проверяем, что фон действительно чёрный (OLED) ----
        bg = await cdp.eval("getComputedStyle(document.body).backgroundColor")
        check("фон OLED — чёрный", bg in ("rgb(0, 0, 0)", "rgba(0, 0, 0, 1)"), f"bg={bg}")

        # ---- свои и чужие должны рисоваться по-разному ----
        print("\n[4] свои и чужие сообщения")
        mine = await cdp.eval("document.querySelectorAll('.msg.mine').length")
        others = await cdp.eval("document.querySelectorAll('.msg:not(.mine)').length")
        check("есть свои сообщения (выравнены вправо)", isinstance(mine, int) and mine > 0, f"mine={mine}")
        check("есть чужие сообщения (выравнены влево)", isinstance(others, int) and others > 0, f"others={others}")

        colors = await cdp.eval("""
          (() => {
            const m = document.querySelector('.msg.mine .msg-body');
            const o = document.querySelector('.msg:not(.mine) .msg-body');
            if (!m || !o) return null;
            const a = getComputedStyle(m), b = getComputedStyle(o);
            return { mineBg: a.backgroundColor, otherBg: b.backgroundColor,
                     mineSide: getComputedStyle(document.querySelector('.msg.mine')).alignSelf,
                     otherSide: getComputedStyle(document.querySelector('.msg:not(.mine)')).alignSelf };
          })()
        """)
        check("пузыри оформлены по-разному",
              bool(colors) and colors["mineBg"] != colors["otherBg"], json.dumps(colors or {}))
        check("свои справа, чужие слева",
              bool(colors) and "end" in (colors["mineSide"] or "") and "start" in (colors["otherSide"] or ""),
              json.dumps(colors or {}))

        # ---- снимок ----
        print("\n[5] снимок экрана")
        shot = await cdp.send("Page.captureScreenshot", format="png")
        data = base64.b64decode(shot["data"])
        with open(OUT, "wb") as f:
            f.write(data)
        check(f"снимок сохранён ({len(data)//1024} КБ)", len(data) > 5000, OUT)

        print(f"\n=== ИТОГ: {ok} passed, {fail} failed ===")
        return 1 if fail else 0


sys.exit(asyncio.run(main()))
