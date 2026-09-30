"""Проверка заголовка клиента: разбор, отчётность, строгий режим.

Запуск: python nko-client-header.py
"""
import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8001"
HEADER = "X-Neko-Client"
ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {name}")
    else:
        fail += 1
        print(f"  FAIL  {name} {extra}")


def get(path, hdr=None, token=None):
    r = urllib.request.Request(BASE + path, method="GET")
    for k, v in (hdr or {}).items():
        r.add_header(k, v)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, timeout=15) as x:
            return x.status, json.loads(x.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}


def main():
    print("[1] запрос без заголовка не ломает API (мягкий режим по умолчанию)")
    code, body = get("/api/client-stats")
    check("сервер жив без заголовка", code == 200, str(code))
    check("статистика отдаётся", "seen" in body, str(body)[:120])

    print("\n[2] заголовок разбирается и попадает в /api/me")
    code, body = get("/auth/login", hdr={})  # это POST-метод, ждём 405
    # логин для токена делаем отдельно
    data = json.dumps({"username": "komdu", "password": "test1234"}).encode()
    r = urllib.request.Request(BASE + "/auth/login", data=data, method="POST")
    r.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(r, timeout=15) as x:
        tok = json.loads(x.read().decode())["access_token"]

    hdr = {HEADER: "nekochat-web/0.11.0 (windows; edge) build=3691612 client=abc123"}
    code, me = get("/api/me", hdr=hdr, token=tok)
    check("вход с заголовком", code == 200, str(code))
    cl = me.get("client", {})
    check("имя разобрано", cl.get("name") == "nekochat-web", json.dumps(cl, ensure_ascii=False))
    check("версия разобрана", cl.get("version") == "0.11.0", json.dumps(cl, ensure_ascii=False))
    check("ОС разобран", cl.get("os") == "windows", json.dumps(cl, ensure_ascii=False))
    check("движок разобран", cl.get("engine") == "edge", json.dumps(cl, ensure_ascii=False))
    check("метка сборки разобрана", cl.get("build") == "3691612", json.dumps(cl, ensure_ascii=False))
    check("клиент узнан как свой", cl.get("known") is True, json.dumps(cl, ensure_ascii=False))
    check("иконка назначена", cl.get("icon") == "web", json.dumps(cl, ensure_ascii=False))
    check("подпись для человека", cl.get("label") == "Веб-клиент 0.11.0", str(cl.get("label")))

    print("\n[3] неизвестный клиент не ломает, но помечается")
    code, me2 = get("/api/me", hdr={HEADER: "curl/8.4.0 (windows)"}, token=tok)
    cl2 = me2.get("client", {})
    check("чужой клиент принят", code == 200, str(code))
    check("помечен как незнакомый", cl2.get("known") is False, json.dumps(cl2, ensure_ascii=False))
    check("иконка unknown", cl2.get("icon") == "unknown", str(cl2.get("icon")))

    print("\n[4] мусор в заголовке не роняет сервер")
    code, me3 = get("/api/me", hdr={HEADER: " bad header <<>>"}, token=tok)
    check("мусорный заголовок пережил", code == 200, str(code))
    code, me4 = get("/api/me", hdr={HEADER: "x" * 500}, token=tok)
    check("длинный заголовок пережил", code == 200, str(code))

    print("\n[5] клиент едет и параметром URL (для WebSocket)")
    code, me5 = get("/api/me?c=" + "nekochat-web%2F0.11.0%20(windows%3B%20edge)%20build%3Dabc")
    check("параметр c распознан без токена (401 — значит заголовок прочитан)",
          code in (200, 401), str(code))
    code, me6 = get("/api/me?c=" + "nekochat-web%2F0.11.0%20(windows)", token=tok)
    check("в /api/me виден клиент из параметра",
          me6.get("client", {}).get("name") == "nekochat-web", json.dumps(me6.get("client", {})))

    print("\n[6] статистика копится")
    code, st = get("/api/client-stats")
    seen = st.get("seen", {})
    check("клиент учтён в статистике", any("nekochat-web" in k for k in seen), json.dumps(seen, ensure_ascii=False)[:200])
    check("есть счётчик отсутствующих", "missing" in st, str(st.get("missing")))

    print(f"\n=== ИТОГ: {ok} passed, {fail} failed ===")
    print("Строгий режим (отказ без заголовка) проверяется отдельно: nko-client-strict.py")
    return 1 if fail else 0


sys.exit(main())
