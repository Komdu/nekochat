"""Диагностика стилей md-filled-button: raw CSS-переменные в обеих темах (CDP :9222)."""
import asyncio
import json
import urllib.request

import websockets

EXPR = """(() => {
  const h = document.querySelector('#auth-button');
  if (!h || !h.shadowRoot) return JSON.stringify({err: 'no-md', tag: h && h.tagName});
  const painted = [];
  h.shadowRoot.querySelectorAll('*').forEach(n => {
    const c = getComputedStyle(n).backgroundColor;
    if (c && c !== 'rgba(0, 0, 0, 0)') painted.push((n.tagName + '.' + n.className).toLowerCase() + '=' + c);
  });
  const b = h.shadowRoot.querySelector('.button');
  const cs = getComputedStyle(b);
  return JSON.stringify({
    theme: document.documentElement.dataset.theme + '-' + document.documentElement.dataset.mode,
    painted, radius: cs.borderRadius, color: cs.color,
    cont: cs.getPropertyValue('--_container-color').trim()
  });
})()"""


async def main():
    with urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=5) as r:
        pages = [t for t in json.loads(r.read()) if t.get("type") == "page"]
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
                    return m["result"]["result"].get("value")

        for theme in ("material-light", "material-dark", "win98-light"):
            await ev(f"localStorage.setItem('nk_theme','{theme}'); location.reload(); 'r'")
            await asyncio.sleep(2.2)
            print(theme, "->", await ev(EXPR))


asyncio.run(main())
