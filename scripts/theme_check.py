"""Проверка тем Win98/Material через CDP (клиент должен быть запущен с --debug).

    python scripts/theme_check.py

Меряет вычисленные стили: шрифт, радиусы кнопок/карточек, тени elevation.
"""
import asyncio
import json
import urllib.request

import websockets


def targets():
    with urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=5) as r:
        pages = [t for t in json.loads(r.read()) if t.get("type") == "page"]
    return pages


EXPR = """
(function (theme) {
  localStorage.setItem('nk_theme', theme);
  Theme.apply(theme);
  var btn = document.querySelector('button');
  var card = document.querySelector('.auth-card');
  var b = getComputedStyle(btn), c = getComputedStyle(card), body = getComputedStyle(document.body);
  return JSON.stringify({
    theme: document.documentElement.dataset.theme,
    mode: document.documentElement.dataset.mode,
    font: body.fontFamily.split(',')[0],
    btnRadius: b.borderRadius,
    btnShadow: (b.boxShadow || 'none').slice(0, 70),
    cardRadius: c.borderRadius,
    cardShadow: (c.boxShadow || 'none').slice(0, 70)
  });
})(THEME)
"""


async def measure(ws_url, theme):
    async with websockets.connect(ws_url, open_timeout=10) as ws:
        await ws.send(json.dumps({
            "id": 1, "method": "Runtime.evaluate",
            "params": {"expression": EXPR.replace("THEME", repr(theme).replace("'", '"')),
                       "returnByValue": True},
        }))
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            if msg.get("id") == 1:
                return json.loads(msg["result"]["result"]["value"])


async def main():
    pages = targets()
    if not pages:
        print("CDP-NOT-READY")
        return
    ws_url = pages[0]["webSocketDebuggerUrl"]
    for theme in ("material-light", "material-dark", "win98-light"):
        s = await measure(ws_url, theme)
        print(f"{theme:16} font={s['font']:14} btn.r={s['btnRadius']:6} "
              f"card.r={s['cardRadius']:6} btn.shadow={s['btnShadow']!r} card.shadow={s['cardShadow']!r}")
    print("THEME-CHECK-OK")


asyncio.run(main())
