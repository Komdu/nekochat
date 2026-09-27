"""Проверка тёмного режима MWC-компонентов (клиент с --debug, CDP :9222)."""
import asyncio
import json
import urllib.request

import websockets


async def main():
    with urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=5) as r:
        pages = [t for t in json.loads(r.read()) if t.get("type") == "page"]
    async with websockets.connect(pages[0]["webSocketDebuggerUrl"], open_timeout=10) as ws:
        async def ev(expr, i=[0]):
            i[0] += 1
            await ws.send(json.dumps({"id": i[0], "method": "Runtime.evaluate",
                                      "params": {"expression": expr, "returnByValue": True}}))
            while True:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
                if m.get("id") == i[0]:
                    return m["result"]["result"].get("value")

        await ev("localStorage.setItem('nk_theme','material-dark'); location.reload(); 'r'")
        await asyncio.sleep(2.5)
        out = await ev("""JSON.stringify({
          mode: document.documentElement.dataset.theme + '-' + document.documentElement.dataset.mode,
          colorScheme: getComputedStyle(document.documentElement).colorScheme,
          hasShadow: !!document.querySelector('#auth-button').shadowRoot,
          innerBg: getComputedStyle(document.querySelector('#auth-button').shadowRoot.querySelector('.button')).backgroundColor,
          innerColor: getComputedStyle(document.querySelector('#auth-button').shadowRoot.querySelector('.button')).color,
          bodyBg: getComputedStyle(document.body).backgroundColor,
          font: getComputedStyle(document.body).fontFamily.split(',')[0],
          robotoLoaded: document.fonts.check('16px Roboto')
        })""")
        print("material-dark:", out)
        await ev("localStorage.setItem('nk_theme','material-light'); 'reset'")
        print("DARK-CHECK-DONE")


asyncio.run(main())
