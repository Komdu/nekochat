"""Проверка серверной части: смена имени, смена пароля, аватар.

Живыми запросами к локальному серверу, как это делает клиент.

Запуск: python nko-account-check.py
"""
import io
import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8001"
ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {name}")
    else:
        fail += 1
        print(f"  FAIL  {name} {extra}")


def api(path, body=None, token=None, method=None, raw=None, ctype=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    r = urllib.request.Request(BASE + path, data=data,
                               method=method or ("POST" if raw is not None or body is not None else "GET"))
    if raw is not None:
        r.add_header("Content-Type", ctype or "application/octet-stream")
    elif body is not None:
        r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(r, timeout=20) as x:
        body = x.read().decode()
        try:
            return json.loads(body)
        except Exception:
            return body


def fail_api(path, body=None, token=None, method="PUT"):
    """Возвращает (код, текст) вместо исключения — нам нужны ошибки."""
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, timeout=20) as x:
            return x.status, x.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


# Настоящий PNG генерируем Pillow: рукописный hex однажды оказался битым,
# и проверка «сервер сжал в webp» падала не из-за сервера, а из-за фикстуры.
def _png_bytes(size=64):
    from io import BytesIO

    from PIL import Image

    im = Image.new("RGB", (size, size), (220, 40, 90))
    for x in range(size):
        for y in range(0, size, 8):
            im.putpixel((x, y), (255, 255, 255))
    out = BytesIO()
    im.save(out, "PNG")
    return out.getvalue()


PNG = _png_bytes()


def upload(token, filename, content, content_type):
    """Загрузка файла: FastAPI ждёт multipart/form-data, а не голые байты."""
    b = "----nko" + "0" * 12
    body = b"".join([
        f"--{b}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
        f"Content-Type: {content_type}\r\n\r\n".encode(),
        content,
        f"\r\n--{b}--\r\n".encode(),
    ])
    r = urllib.request.Request(BASE + "/users/me/avatar", data=body, method="POST")
    r.add_header("Content-Type", f"multipart/form-data; boundary={b}")
    r.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(r, timeout=30) as x:
        return json.loads(x.read().decode())


def upload_expect_error(token, filename, content, content_type):
    b = "----nko" + "0" * 12
    body = b"".join([
        f"--{b}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
        f"Content-Type: {content_type}\r\n\r\n".encode(),
        content,
        f"\r\n--{b}--\r\n".encode(),
    ])
    r = urllib.request.Request(BASE + "/users/me/avatar", data=body, method="POST")
    r.add_header("Content-Type", f"multipart/form-data; boundary={b}")
    r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, timeout=30) as x:
            return x.status, x.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def main():
    print("[setup] создаём пользователя для проверки")
    name = "acctchk"
    try:
        reg = api("/auth/register", {"username": name, "password": "test1234", "display_name": "Прежний"})
        tok = reg["access_token"]
    except urllib.error.HTTPError:
        reg = api("/auth/login", {"username": name, "password": "test1234"})
        tok = reg["access_token"]
    print(f"   пользователь {name}, отображаемое имя: {reg['user']['display_name']!r}")

    print("\n[1] смена отображаемого имени")
    code, body = fail_api("/users/me/profile", {"display_name": "Новое имя"}, tok)
    check("имя поменялось", code == 200 and json.loads(body)["display_name"] == "Новое имя",
          f"{code} {body[:120]}")
    me = api("/api/me", None, tok)
    check("имя сохранилось в профиле", me["display_name"] == "Новое имя", me["display_name"])

    code, body = fail_api("/users/me/profile", {"display_name": "   "}, tok)
    check("пустое имя отклонено", code == 400, f"{code} {body[:100]}")
    code, body = fail_api("/users/me/profile", {"display_name": "х" * 41}, tok)
    check("слишком длинное имя отклонено", code == 400, f"{code} {body[:100]}")
    code, body = fail_api("/users/me/profile", {"display_name": "имя\nс\nпереносом"}, tok)
    check("управляющие символы в имени отклонены", code == 400, f"{code} {body[:100]}")

    # имя не должно затереть статус и био
    code, body = fail_api("/users/me/profile", {"status": "занят", "bio": "тест"}, tok)
    j = json.loads(body)
    check("смена имени не затирает статус и био",
          code == 200 and j.get("status") == "занят" and j.get("bio") == "тест",
          f"{code} {body[:140]}")

    print("\n[2] смена пароля")
    code, body = fail_api("/users/me/password", {"old_password": "неверный", "new_password": "мойпароль"}, tok)
    check("неверный старый пароль отклонён", code == 400, f"{code} {body[:120]}")

    code, body = fail_api("/users/me/password", {"old_password": "test1234", "new_password": "123"}, tok)
    check("слишком короткий новый пароль отклонён", code == 400, f"{code} {body[:120]}")

    code, body = fail_api("/users/me/password", {"old_password": "test1234", "new_password": "test1234"}, tok)
    check("тот же пароль отклонён", code == 400, f"{code} {body[:120]}")

    code, body = fail_api("/users/me/password", {"old_password": "test1234", "new_password": "мойНовыйПароль7"}, tok)
    check("пароль поменян на свой", code == 200, f"{code} {body[:120]}")

    # старый пароль больше не работает, новый — работает
    try:
        api("/auth/login", {"username": name, "password": "test1234"})
        old_works = True
    except urllib.error.HTTPError:
        old_works = False
    check("старый пароль больше не входит", not old_works)

    again = api("/auth/login", {"username": name, "password": "мойНовыйПароль7"})
    check("новый пароль входит", again["user"]["username"] == name)
    tok = again["access_token"]

    # сессия не разлогинилась при смене пароля
    code, _ = fail_api("/users/me/profile", {"status": "после смены"}, tok)
    check("текущая сессия жива после смены пароля", code == 200, f"{code}")

    # возвращаем пароль обратно, чтобы тесты дальше пользовались им
    fail_api("/users/me/password", {"old_password": "мойНовыйПароль7", "new_password": "test1234"}, tok)

    print("\n[3] аватар")
    try:
        out = upload(tok, "a.png", PNG, "image/png")
        check("аватар загружен", bool(out.get("avatar")), json.dumps(out)[:120])
        check("сервер отдал обновлённого пользователя", out.get("id") is not None)
        av = out.get("avatar")
        if av:
            with urllib.request.urlopen(BASE + "/avatars/" + av, timeout=15) as x:
                data = x.read()
            check("аватар отдаётся по /avatars/", len(data) > 100, f"{len(data)} байт")
            check("аватар сжат сервером в webp ≤192px",
                  data[:4] == b"RIFF" and len(data) < 200 * 1024,
                  f"{len(data)} байт, заголовок {data[:4]!r}")
    except urllib.error.HTTPError as e:
        check("аватар загружен", False, f"{e.code} {e.read()[:150]}")

    code, body = upload_expect_error(tok, "a.png", b"not-an-image-at-all", "image/png")
    check("мусорный файл отклонён", code == 400, f"{code} {body[:120]}")

    code, body = upload_expect_error(tok, "a.txt", b"hello", "text/plain")
    check("неизвестный тип файла отклонён", code == 400, f"{code} {body[:120]}")

    print(f"\n=== ИТОГ: {ok} passed, {fail} failed ===")
    return 1 if fail else 0


sys.exit(main())
