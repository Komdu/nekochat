"""Headless-проверка client_ui.api против живого сервера (без GUI)."""
import sys
import time

sys.path.insert(0, r"D:\nekochat")

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from PySide6.QtCore import QCoreApplication

from client_ui.api import ApiClient

BASE = "http://127.0.0.1:8765"
app = QCoreApplication(sys.argv[:1])
ts = str(int(time.time()))

A = ApiClient(BASE)
B = ApiClient(BASE)
results = []


def check(name, cond):
    print(("OK  " if cond else "FAIL") + " " + name)
    results.append(cond)


def wait_until(fn, timeout=12.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if fn():
            return True
        time.sleep(0.01)
    return False


done = {"wsA": False, "echo": None, "dmB": None, "dmA": None}


def after_auth(api, name):
    def _ok(user):
        print(f"  {name} authed id={user.get('id')}")
        done[f"{name}auth"] = True
    return _ok


def setup_auth(api, username, display):
    api.register(username, "secret123", display, after_auth(api, username), lambda m: print("reg fail", m))


setup_auth(A, "uA_" + ts, "TeстA")
setup_auth(B, "uB_" + ts, "TeстB")
assert wait_until(lambda: done.get("uA_" + ts + "auth") and done.get("uB_" + ts + "auth"), 15), "auth timeout"
check("register+login", True)
check("me_id set", A.me_id and B.me_id)

# комната
room_id = {"v": None}
A.create_room("комната_" + ts, lambda r: room_id.__setitem__("v", r.get("id")), print)
assert wait_until(lambda: room_id["v"] is not None), "room timeout"
check("create_room", room_id["v"] is not None)

# WS: комнатное сообщение
A.ws_open()
B.ws_open()
assert wait_until(lambda: A.socket.state().name == "ConnectedState"), "A ws timeout"
assert wait_until(lambda: B.socket.state().name == "ConnectedState"), "B ws timeout"
check("ws_connected (A/B)", True)


def on_room(room_id_, msg):
    done["echo"] = (room_id_, msg)


A.ws_room_message.connect(on_room)
A.send_room(room_id["v"], "привет из нативного клиента")
assert wait_until(lambda: done["echo"] is not None), "echo timeout"
check("ws room_message echo", done["echo"] and done["echo"][1].get("content", "").startswith("привет"))
print("  echo:", done["echo"])

# ЛС: A -> B
def on_dm(conv, frm, msg):
    if frm == A.me_id:        # B получил сообщение от A
        done["dmB"] = msg
    elif frm == B.me_id:      # A получил эхо собственного сообщения
        done["dmA"] = msg


B.ws_dm_message.connect(on_dm)
A.send_dm(B.me_id, "личное от A")
assert wait_until(lambda: done["dmB"] is not None), "dm timeout"
check("ws dm_message (B got)", done["dmB"] is not None and done["dmB"].get("content") == "личное от A")

# история ЛС
hist = {"v": None}
A.dm_messages(B.me_id, lambda m: hist.__setitem__("v", m))
assert wait_until(lambda: hist["v"] is not None), "dms history timeout"
check("dm history", any(m.get("content") == "личное от A" for m in (hist["v"] or [])))

# переписки и люди
conv = {"v": None}; us = {"v": None}
A.conversations(lambda m: conv.__setitem__("v", m))
A.users(lambda m: us.__setitem__("v", m))
assert wait_until(lambda: conv["v"] is not None and us["v"] is not None), "conv/users timeout"
check("conversations list", conv["v"])
check("users list excludes me", all(u.get("id") != A.me_id for u in (us["v"] or [])))

# история комнаты через REST
rm = {"v": None}
A.room_messages(room_id["v"], lambda m: rm.__setitem__("v", m))
assert wait_until(lambda: rm["v"] is not None), "room history timeout"
check("room history has msg", any(m.get("content", "").startswith("привет") for m in (rm["v"] or [])))

ok = all(results)
print("---")
print("CLIENT-API-SMOKE:", "OK" if ok else "FAIL")

# чистый выход: закрыть WS и дать событиям разойтись
A.socket.close()
B.socket.close()
end = time.time() + 1.0
while time.time() < end:
    app.processEvents()
    time.sleep(0.01)
app.quit()
sys.exit(0 if ok else 1)