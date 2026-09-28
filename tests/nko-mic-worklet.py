"""Микрофонный воркер: проверяем в настоящем браузере.

Главное, что тут ловится, — РАЗМЕР КАДРА. Раньше воркер отдавал каждый квант
по 128 сэмплов (2,7 мс), а энкодер Opus ждёт кадры по 20 мс (960 сэмплов) и
двигает метку времени на 20 мс. На провод уходило ~375 пакетов в секунду вместо
50, а метки времени разъезжались.

Сигнал синтезируется прямо в тесте — микрофон не нужен.

Запуск: python nko-mic-worklet.py [url]
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
PORT = 9339
PROF = r"C:\Users\Komdu\AppData\Local\Temp\nko-edge-mic"
URL = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5173/web_next/").rstrip("/") + "/"

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
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    async def eval(self, expr, note=""):
        r = await self.send("Runtime.evaluate", expression=expr, awaitPromise=True,
                            returnByValue=True)
        if r.get("exceptionDetails"):
            ex = r["exceptionDetails"].get("exception", {})
            raise RuntimeError(f"{note}: {ex.get('description', '?')[:200]}")
        return r.get("result", {}).get("value")


PROBE = r"""
(async () => {
  const out = { frames: [], err: null };
  try {
    const ctx = new AudioContext({ sampleRate: 48000 });
    await ctx.resume();
    out.ctxRate = ctx.sampleRate;

    const src = window.__nkoMicSrc;
    if (!src) throw new Error('исходник воркера не найден (нужен dev-сервер)');
    out.srcLen = src.length;
    out.hasFrame960 = /frameN = 960/.test(src);

    const url = URL.createObjectURL(new Blob([src], { type: 'application/javascript' }));
    await ctx.audioWorklet.addModule(url);
    out.moduleOk = true;

    const node = new AudioWorkletNode(ctx, 'mic-capture');
    node.port.onmessage = (e) => {
      const d = e.data || {};
      if (d.ev === 'audio' && d.pcm) out.frames.push(d.pcm.length);
    };

    // 2 секунды тона 440 Гц
    const rate = 48000, total = rate * 2;
    const buf = new Float32Array(total);
    for (let i = 0; i < total; i++) buf[i] = 0.3 * Math.sin(2 * Math.PI * 440 * i / rate);
    const ab = ctx.createBuffer(1, total, rate);
    ab.copyToChannel(buf, 0);
    const srcNode = ctx.createBufferSource();
    srcNode.buffer = ab;
    srcNode.connect(node);
    const sink = ctx.createGain();
    sink.gain.value = 0;
    node.connect(sink);
    sink.connect(ctx.destination);
    srcNode.start();
    await new Promise(r => setTimeout(r, 2600));
    srcNode.stop();
    return out;
  } catch (err) {
    out.err = String(err && err.message || err);
    return out;
  }
})()
"""


async def main():
    subprocess.run(["taskkill", "/F", "/IM", "msedge.exe"], capture_output=True)
    shutil.rmtree(PROF, ignore_errors=True)
    proc = subprocess.Popen(
        [EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
         "--no-default-browser-check", "--autoplay-policy=no-user-gesture-required",
         f"--remote-debugging-port={PORT}", f"--user-data-dir={PROF}",
         "--window-size=1000,700", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ws_url = None
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=2) as r:
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
        await cdp.send("Page.navigate", url=URL)
        await asyncio.sleep(4)

        res = await cdp.eval(PROBE)
        if res.get("err"):
            check("проба выполнилась без ошибок", False, res["err"][:200])
            proc.kill()
            return 1

        print(f"   контекст {res.get('ctxRate')} Гц, исходник {res.get('srcLen')} Б")
        check("контекст 48 кГц", res.get("ctxRate") == 48000, str(res.get("ctxRate")))
        check("воркер загрузился", bool(res.get("moduleOk")))

        frames = res.get("frames") or []
        sizes = sorted(set(frames))
        print(f"   получено кадров: {len(frames)}, размеры: {sizes}")
        check("кадры приходят", len(frames) > 0, "ни одного кадра")
        check("все кадры ровно по 960 сэмплов (20 мс)", sizes == [960], str(sizes))
        # 2 секунды -> ~100 кадров по 20 мс
        check("за 2 с пришло ~100 кадров, а не ~750", 70 <= len(frames) <= 130, f"кадров={len(frames)}")

    proc.kill()
    print(f"\n=== ИТОГ: {ok} passed, {fail} failed ===")
    return 1 if fail else 0


sys.exit(asyncio.run(main()))
