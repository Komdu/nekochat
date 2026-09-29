"""Проверяем, что Speex реально подавляет шум в настоящем браузере.

Ставим SpeexWorkletNode в реальный аудио-граф (без микрофона: сигнал
синтезируем) и смотрим, что на выходе шума меньше, чем на входе, а речь
осталась. Это ровно та проверка, которой был завален RNNoise: там модуль
загружался, не падал, но сигнал не менялся.

Запуск: python nko-speex-check.py [url]
"""
import asyncio
import json
import math
import shutil
import subprocess
import sys
import time
import urllib.request

import websockets

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 9340
PROF = r"C:\Users\Komdu\AppData\Local\Temp\nko-edge-speex"
URL = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8001/web_next/").rstrip("/") + "/"

ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {name}")
    else:
        fail += 1
        print(f"  FAIL  {name} {extra}")


def db(v):
    if v <= 0:
        return -120.0
    return round(20 * math.log10(v), 1)


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
            raise RuntimeError(f"{note}: {ex.get('description', '?')[:300]}")
        return r.get("result", {}).get("value")


PROBE = r"""
(async () => {
  const out = { err: null };
  try {
    // функции берём из dev-хука: это ровно то, чем пользуется клиент, а не копия
    const ns = window.__nkoNs;
    if (!ns) { out.err = 'нет dev-хука __nkoNs (нужен dev-сервер)'; return out; }
    const wasm = await ns.loadSpeexWasm();
    out.wasmBytes = wasm ? wasm.byteLength : 0;
    if (!wasm) { out.err = 'wasm не загрузился'; return out; }

    const ctx = new AudioContext({ sampleRate: 48000 });
    await ctx.resume();
    out.rate = ctx.sampleRate;

    const sp = await ns.createSpeexNode(ctx, wasm);
    out.nodeOk = !!sp.node;
    sp.node.connect(ctx.destination);

    // синтезируем 6 секунд: речь-like + постоянный шум
    const SR = 48000, total = SR * 6;
    const buf = new Float32Array(total);
    let seed = 7;
    const rnd = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return (seed / 0x7fffffff) * 2 - 1; };
    for (let i = 0; i < total; i++) {
      const t = i / SR;
      const syl = Math.pow(Math.max(0, Math.sin(2 * Math.PI * 3 * t)), 2);
      const f0 = 120 + 20 * Math.sin(2 * Math.PI * 1.5 * t);
      let v = 0;
      for (let h = 1; h <= 10; h++) v += (0.9 / h) * Math.sin(2 * Math.PI * f0 * h * t + h);
      buf[i] = 0.30 * syl * v + 0.10 * rnd();
    }

    // считаем RMS входа и выхода по окнам
    const WIN = 4800; // 100 мс
    const rin = [], rout = [];
    const an = ctx.createAnalyser(); an.fftSize = 8192;
    sp.node.connect(an);
    const src = ctx.createBufferSource();
    const ab = ctx.createBuffer(1, total, SR);
    ab.copyToChannel(buf, 0);
    src.buffer = ab;
    src.connect(sp.node);
    src.start();

    const time = new Float32Array(an.fftSize);
    const freqs = new Uint8Array(an.frequencyBinCount);
    const start = performance.now();
    while (performance.now() - start < 6200) {
      await new Promise(r => setTimeout(r, 90));
      an.getFloatTimeDomainData(time);
      let s = 0;
      for (let i = 0; i < time.length; i++) s += time[i] * time[i];
      rout.push(Math.sqrt(s / time.length));
    }
    src.stop();
    // вход считаем отдельно, окнами той же длины
    for (let o = 0; o + WIN <= total; o += WIN) {
      let s = 0;
      for (let i = 0; i < WIN; i++) s += buf[o + i] * buf[o + i];
      rin.push(Math.sqrt(s / WIN));
    }
    out.rin = rin;
    out.rout = rout;
    out.nIn = rin.length;
    out.nOut = rout.length;
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

        # wasm отдаём хуком из main.ts
        hook = await cdp.eval("({ wasm: window.__nkoSpeexWasm || null })")
        if not hook.get("wasm"):
            print("нет хука __nkoSpeexWasm — добавь его в web/src/main.ts")
            proc.kill()
            return 1
        await cdp.eval(f"window.__nkoSpeexWasm = {json.dumps(hook['wasm'])};")

        res = await cdp.eval(PROBE)
        if res.get("err"):
            check("проба выполнилась", False, res["err"][:250])
            proc.kill()
            return 1

        print(f"   wasm {res.get('wasmBytes')} Б, узел создан: {res.get('nodeOk')}")
        check("wasm Speex загрузился", (res.get("wasmBytes") or 0) > 40000, str(res.get("wasmBytes")))
        check("узел Speex создан", bool(res.get("nodeOk")))

        rin = res.get("rin") or []
        rout = res.get("rout") or []
        print(f"   окон входа {len(rin)}, окон выхода {len(rout)}")
        if len(rout) < 10:
            check("вышло достаточно данных", False, f"окон={len(rout)}")
            proc.kill()
            return 1

        # сопоставляем окна: выход задержан на несколько окон, ищем лучший сдвиг
        best = None
        for shift in range(0, 12):
            if len(rout) - shift <= 0:
                break
            rin_al = rin[:len(rout) - shift]
            rout_al = rout[shift:]
            n = min(len(rin_al), len(rout_al))
            if n < 10:
                continue
            ri = sum(rin_al[:n]) / n
            ro = sum(rout_al[:n]) / n
            red = db(ri) - db(ro)
            if best is None or red > best[0]:
                best = (red, shift, ri, ro)
        if best:
            red, shift, ri, ro = best
            print(f"   вход {db(ri):.1f} дБ -> выход {db(ro):.1f} дБ  "
                  f"(сдвиг {shift} окон, подавление {red:+.1f} дБ)")
            check("Speex ослабляет сигнал (шумодав работает)", red > 1.5, f"{red:+.1f} дБ")
        else:
            check("Speex ослабляет сигнал (шумодав работает)", False, "не хватило окон")

        quiet = sorted(rout)[:max(1, len(rout) // 4)]
        loud = sorted(rout)[-max(1, len(rout) // 4):]
        print(f"   тихие окна {db(sum(quiet)/len(quiet)):.1f} дБ, "
              f"громкие {db(sum(loud)/len(loud)):.1f} дБ")
        check("динамический диапазон сохранился (речь не срезана в ноль)",
              db(sum(loud) / len(loud)) > db(sum(quiet) / len(quiet)) + 3.0,
              f"{db(sum(loud)/len(loud)):.1f} против {db(sum(quiet)/len(quiet)):.1f}")

    proc.kill()
    print(f"\n=== ИТОГ: {ok} passed, {fail} failed ===")
    return 1 if fail else 0


sys.exit(asyncio.run(main()))
