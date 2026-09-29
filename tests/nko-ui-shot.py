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

        # ---- диалоги: настройки и создание комнаты ----
        print("\n[5] диалоги")
        # открыть настройки кликом по кнопке в подвале
        await cdp.eval("""
          (() => {
            const btns = Array.from(document.querySelectorAll('.side-foot button'));
            const b = btns.find(x => x.title === 'Настройки');
            if (b) { b.click(); return true; }
            return false;
          })()
        """)
        await asyncio.sleep(0.8)
        dlg = await cdp.eval("!!document.querySelector('.dlg-card')")
        check("настройки открылись", bool(dlg))
        themes = await cdp.eval("document.querySelectorAll('.theme').length")
        check("доступны три темы (oled/material/win98)", themes == 3, f"themes={themes}")

        # переключаем тему на win98 -> ждём смены data-theme
        await cdp.eval("""
          (() => {
            const t = Array.from(document.querySelectorAll('.theme'))
              .find(x => x.textContent.includes('Win98'));
            if (t) t.click();
            return true;
          })()
        """)
        await asyncio.sleep(0.8)
        th2 = await cdp.eval("document.documentElement.dataset.theme")
        check("тема переключилась на win98", th2 == "win98", f"theme={th2}")
        ls_theme = await cdp.eval("localStorage.getItem('nk_theme')")
        check("выбор темы сохранён в localStorage", ls_theme == "win98-dark", f"ls={ls_theme}")

        # возвращаем OLED (основная тема) и закрываем по Esc
        await cdp.eval("""
          (() => {
            const t = Array.from(document.querySelectorAll('.theme'))
              .find(x => x.textContent.includes('OLED'));
            if (t) t.click();
            return true;
          })()
        """)
        await asyncio.sleep(0.5)
        th3 = await cdp.eval("document.documentElement.dataset.theme")
        check("вернулись на OLED", th3 == "oled", f"theme={th3}")

        await cdp.send("Input.dispatchKeyEvent", type="keyDown", key="Escape", code="Escape", windowsVirtualKeyCode=27)
        await cdp.send("Input.dispatchKeyEvent", type="keyUp", key="Escape", code="Escape", windowsVirtualKeyCode=27)
        await asyncio.sleep(0.6)
        closed = await cdp.eval("!document.querySelector('.dlg-card')")
        check("диалог закрылся по Esc", bool(closed))

        # ---- профиль: имя, пароль, аватар ----
        print("\n[6] профиль")
        # диалог настроек после проверки тем закрыт по Esc — открываем заново
        await cdp.eval("""
          (() => {
            const b = Array.from(document.querySelectorAll('.side-foot button'))
              .find(x => x.title === 'Настройки');
            if (b) { b.click(); return true; }
            return false;
          })()
        """)
        await asyncio.sleep(0.8)
        has_name = await cdp.eval("""
          Array.from(document.querySelectorAll('.dlg-card .field > span'))
            .some(e => e.textContent.trim() === 'Отображаемое имени')
        """.replace('Отображаемое имени', 'Отображаемое имя'))
        check("есть поле отображаемого имени", bool(has_name))
        has_pass = await cdp.eval("""
          Array.from(document.querySelectorAll('.dlg-card .field > span'))
            .some(e => e.textContent.trim() === 'Текущий пароль')
        """)
        check("есть блок смены пароля", bool(has_pass))
        has_pick = await cdp.eval("!!document.querySelector('.dlg-card input[type=file]')")
        check("есть выбор файла для аватарки", bool(has_pick))

        new_name = "Проверка-" + str(int(time.time()))[-4:]
        await cdp.eval("""
          (() => {
            const spans = Array.from(document.querySelectorAll('.dlg-card .field > span'));
            const lbl = spans.find(e => e.textContent.trim() === 'Отображаемое имя');
            const inp = lbl.parentElement.querySelector('input');
            const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
            s.call(inp, %s);
            inp.dispatchEvent(new Event('input', { bubbles: true }));
            return true;
          })()
        """ % json.dumps(new_name))
        await asyncio.sleep(0.3)
        await cdp.eval("""
          (() => {
            const b = Array.from(document.querySelectorAll('.dlg-foot button'))
              .find(x => x.textContent.trim() === 'Сохранить');
            if (b) { b.click(); return true; }
            return false;
          })()
        """)
        await asyncio.sleep(2.0)
        saved = await cdp.eval(
            "JSON.parse(localStorage.getItem('nk.user') || '{}').display_name === %s" % json.dumps(new_name))
        check("имя сохранилось в клиенте", bool(saved),
              str(await cdp.eval("JSON.stringify(JSON.parse(localStorage.getItem('nk.user')||{}).display_name)")))
        in_sidebar = await cdp.eval(
            "(document.querySelector('.side-foot .me-name') || {}).textContent === %s" % json.dumps(new_name))
        check("новое имя видно в списке без перезагрузки", bool(in_sidebar))

        # неверный старый пароль: ошибка, а не молчание; сессия жива
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
            const spans = Array.from(document.querySelectorAll('.dlg-card .field > span'));
            const set = (label, val) => {
              const lbl = spans.find(e => e.textContent.trim() === label);
              if (!lbl) return false;
              const inp = lbl.parentElement.querySelector('input');
              const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
              s.call(inp, val);
              inp.dispatchEvent(new Event('input', { bubbles: true }));
              return true;
            };
            set('Текущий пароль', 'wrong-password');
            set('Новый пароль', 'brandNew7pass');
            set('Новый пароль ещё раз', 'brandNew7pass');
            return true;
          })()
        """)
        await asyncio.sleep(0.3)
        await cdp.eval("""
          (() => {
            const b = Array.from(document.querySelectorAll('.dlg-card button'))
              .find(x => x.textContent.trim() === 'Сменить пароль');
            if (b) { b.click(); return true; }
            return false;
          })()
        """)
        await asyncio.sleep(1.5)
        pass_err = await cdp.eval("((document.querySelector('.dlg-err') || {}).textContent || '')")
        check("неверный старый пароль даёт ошибку", bool(pass_err), str(pass_err)[:100])
        still_in = await cdp.eval("!!document.querySelector('.side')")
        check("после неудачной смены пароля сессия жива", bool(still_in))

        # аватар настоящим файлом
        png_b64 = ("iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAOklEQVR42u3OMQEAAAgDoC251a3g"
                   "LwaSUGoQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
                   "AAAAAAAAAAAAAADgvwZ0mAABZbQ3kwAAAABJRU5ErkJggg==")
        await cdp.eval("""
          (async () => {
            const bin = atob(%s);
            const arr = new Uint8Array(bin.length);
            for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
            const file = new File([arr], 'a.png', { type: 'image/png' });
            const dt = new DataTransfer();
            dt.items.add(file);
            const inp = document.querySelector('.dlg-card input[type=file]');
            inp.files = dt.files;
            inp.dispatchEvent(new Event('change', { bubbles: true }));
            return true;
          })()
        """ % json.dumps(png_b64))
        await asyncio.sleep(3.0)
        av = await cdp.eval("JSON.parse(localStorage.getItem('nk.user')||{}).avatar")
        check("аватар загрузился", bool(av), str(av))
        shown = await cdp.eval("!!document.querySelector('.me-row .avatar img')")
        check("картинка показана вместо инициалов", bool(shown))

        await cdp.send("Input.dispatchKeyEvent", type="keyDown", key="Escape", code="Escape", windowsVirtualKeyCode=27)
        await cdp.send("Input.dispatchKeyEvent", type="keyUp", key="Escape", code="Escape", windowsVirtualKeyCode=27)
        await asyncio.sleep(0.5)

        # создание комнаты
        await cdp.eval("""
          (() => {
            const b = Array.from(document.querySelectorAll('.side-head button'))
              .find(x => x.title === 'Создать комнату');
            if (b) { b.click(); return true; }
            return false;
          })()
        """)
        await asyncio.sleep(0.8)
        check("диалог создания комнаты открылся",
              bool(await cdp.eval("!!document.querySelector('.dlg-card')")))

        # вводим название и создаём
        room_name = "проверка-" + str(int(time.time()))[-5:]
        await cdp.eval("""
          (() => {
            const inp = document.querySelector('.dlg-card input');
            const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            s.call(inp, %s);
            inp.dispatchEvent(new Event('input', { bubbles: true }));
            return true;
          })()
        """ % json.dumps(room_name))
        await asyncio.sleep(0.3)
        await cdp.eval("""
          (() => {
            const b = Array.from(document.querySelectorAll('.dlg-foot button'))
              .find(x => x.textContent.trim() === 'Создать');
            if (b) { b.click(); return true; }
            return false;
          })()
        """)
        await asyncio.sleep(2.5)
        created = await cdp.eval("""
          Array.from(document.querySelectorAll('.list-item .item-name'))
            .some(e => e.textContent.trim() === %s)
        """ % json.dumps(room_name))
        check("комната появилась в списке", bool(created), room_name)
        opened = await cdp.eval(
            "(document.querySelector('.title-text') || {}).textContent === %s" % json.dumps(room_name))
        check("новая комната сразу открыта", bool(opened))

        # ---- снимок ----
        print("\n[7] снимок экрана")
        shot = await cdp.send("Page.captureScreenshot", format="png")
        data = base64.b64decode(shot["data"])
        with open(OUT, "wb") as f:
            f.write(data)
        check(f"снимок сохранён ({len(data)//1024} КБ)", len(data) > 5000, OUT)

        print(f"\n=== ИТОГ: {ok} passed, {fail} failed ===")
        return 1 if fail else 0


sys.exit(asyncio.run(main()))
