"""Проверка Material You через CDP (клиент с --debug, CDP :9222).

    python scripts/you_check.py

Что проверяется:
  1. пресет (blue): inline-токены --md-sys-color-primary отличаются от #6750a4
     и фон md-кнопки равен этому токену;
  2. живое переключение свотчем pink БЕЗ перезагрузки (localStorage + токены);
  3. тёмный режим с пресетом: primary меняется;
  4. secondary-кнопки стали md-filled-tonal-button;
  5. карточка авторизации radius 28px;
  6. win98: свотчи скрыты, md нет, inline-токены сняты;
  7. контраст светлого primary к белому тексту >= 4.0 (WCAG).
"""
import asyncio
import json
import urllib.request

import websockets


def rel_lum(hex_color):
    n = int(hex_color.lstrip("#"), 16)
    f = lambda c: (c / 255) / 12.92 if c <= 10 else (((c / 255) + 0.055) / 1.055) ** 2.4
    r, g, b = (n >> 16) & 255, (n >> 8) & 255, n & 255
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(l1, l2):
    a, b = max(l1, l2), min(l1, l2)
    return (a + 0.05) / (b + 0.05)


async def main():
    with urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=5) as r:
        pages = [t for t in json.loads(r.read()) if t.get("type") == "page"]
    if not pages:
        print("CDP-NOT-READY")
        return
    async with websockets.connect(pages[0]["webSocketDebuggerUrl"], open_timeout=10) as ws:
        i = 0

        async def ev(expr):
            nonlocal i
            i += 1
            await ws.send(json.dumps({"id": i, "method": "Runtime.evaluate",
                                      "params": {"expression": expr, "returnByValue": True}}))
            while True:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
                if m.get("id") == i:
                    res = m["result"]["result"]
                    if m["result"].get("exceptionDetails"):
                        return {"error": m["result"]["exceptionDetails"].get("text", "exception")}
                    return res.get("value")

        async def set_theme(theme, you=None, reload=True):
            y = f"localStorage.setItem('nk_you_color','{you}');" if you is not None else \
                "localStorage.removeItem('nk_you_color');"
            await ev(f"localStorage.setItem('nk_theme','{theme}'); {y}"
                     + ("location.reload(); 'r'" if reload else "'ok'"))
            if reload:
                await asyncio.sleep(2.3)

        # --- 1. пресет blue, светлая тема ---
        await set_theme("material-light", you="blue")
        blue_raw = await ev("""JSON.stringify({
          you: window.You && You.current(),
          primary: document.documentElement.style.getPropertyValue('--md-sys-color-primary'),
          btnPainted: (() => { const h = document.querySelector('#auth-button');
            const out = [];
            h.shadowRoot.querySelectorAll('*').forEach(n => {
              const c = getComputedStyle(n).backgroundColor;
              if (c && c !== 'rgba(0, 0, 0, 0)') out.push(c); });
            return out[0]; })(),
          title1: document.documentElement.style.getPropertyValue('--title1'),
          radius: getComputedStyle(document.querySelector('.auth-card')).borderRadius,
          tonal: (document.querySelector('#modal-cancel') || {}).tagName
        })""")
        blue = json.loads(blue_raw) if isinstance(blue_raw, str) else blue_raw
        print("1 preset-blue:", blue)

        # --- 7. контраст primary/белый ---
        if blue and blue.get("primary"):
            cr = contrast(rel_lum(blue["primary"]), 1.0)
            print(f"7 contrast white on {blue['primary']}: {cr:.2f}",
                  "OK" if cr >= 4.0 else "LOW!")
        else:
            print("7 contrast: SKIPPED (no primary)")

        # --- 2. живое переключение свотчем pink (без reload) ---
        await ev("""(() => { document.querySelector('.you-swatch[data-you=pink]').click(); return 'clicked'; })()""")
        await asyncio.sleep(0.3)
        pink = await ev("""JSON.stringify({
          you: localStorage.getItem('nk_you_color'),
          primary: document.documentElement.style.getPropertyValue('--md-sys-color-primary'),
          active: document.querySelector('.you-swatch[data-you=pink]').classList.contains('active'),
          noReload: performance.getEntriesByType('navigation').length === 1
        })""")
        pink = json.loads(pink) if isinstance(pink, str) else pink
        print("2 live-pink:", pink)

        # --- 3. тёмный режим с пресетом ---
        await set_theme("material-dark", you="blue")
        dark = await ev("""JSON.stringify({
          primary: document.documentElement.style.getPropertyValue('--md-sys-color-primary'),
          mode: document.documentElement.dataset.mode
        })""")
        dark = json.loads(dark) if isinstance(dark, str) else dark
        print("3 dark-blue:", dark)

        # --- 4/5. тональная кнопка и радиус уже были в шаге 1, повторим в тёмной ---
        extra = await ev("""JSON.stringify({
          tonal: (document.querySelector('#modal-cancel') || {}).tagName,
          radius: getComputedStyle(document.querySelector('.auth-card')).borderRadius
        })""")
        extra = json.loads(extra) if isinstance(extra, str) else extra
        print("4/5:", extra)

        # --- 6. win98 ---
        await set_theme("win98-light", you="blue")
        w = await ev("""JSON.stringify({
          mdCount: document.querySelectorAll('md-filled-button, md-filled-tonal-button, md-outlined-text-field').length,
          inlinePrimary: document.documentElement.style.getPropertyValue('--md-sys-color-primary'),
          youGroup: getComputedStyle(document.querySelector('.you-group')).display,
          nativeBtn: (document.querySelector('#auth-button') || {}).tagName
        })""")
        w = json.loads(w) if isinstance(w, str) else w
        print("6 win98:", w)

        # --- сброс к дефолту для пользователя ---
        await set_theme("material-light", you=None)
        print("YOU-CHECK-DONE")


asyncio.run(main())
