"""API-клиент нативного приложения: REST (QNetworkAccessManager) + WebSocket (QWebSocket).

Реализует контракт docs/API.md: /auth, /api/me, /rooms, /users, /avatars, WS /ws?token=.
Все вызовы асинхронные: ok(json) / err(message).
"""
import json
import os

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import (
    QHttpMultiPart,
    QHttpPart,
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
)
from PySide6.QtWebSockets import QWebSocket, QWebSocketProtocol


class ApiClient(QObject):
    """Клиент одного сервера: REST + WS. Создаётся на окно чата."""

    # WS → UI
    ws_connected = Signal()
    ws_closed = Signal(int, str)      # code, reason
    ws_status = Signal(int, bool)     # user_id, online
    ws_room_message = Signal(str, dict)
    ws_dm_message = Signal(int, int, dict)  # conversation_id, from_id, message
    ws_call = Signal(dict)            # сигналинг звонка (P2P), phase 2
    ws_error = Signal(str)
    auth_failed = Signal(str)   # 401 на авторизованном запросе: сессия мертва

    def __init__(self, base_url: str, parent=None):
        super().__init__(parent)
        self.base = base_url.rstrip("/")
        self.nam = QNetworkAccessManager(self)
        self.access_token = None
        self.user = None
        self.me_id = None

        self.socket = QWebSocket("", QWebSocketProtocol.VersionLatest, self)
        self.socket.textMessageReceived.connect(self._on_text)
        self.socket.connected.connect(self.ws_connected)
        self.socket.disconnected.connect(lambda: self.ws_closed.emit(-1, "closed"))
        self.socket.errorOccurred.connect(lambda _e: self.ws_error.emit(self.socket.errorString()))

    # ---------------- REST ----------------

    def _call(self, method, path, payload, ok, err=None, auth=True):
        req = QNetworkRequest(QUrl(self.base + path))
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        if auth and self.access_token:
            req.setRawHeader(b"Authorization", b"Bearer " + self.access_token.encode())
        data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else b""
        if method == "GET":
            reply = self.nam.get(req)
        elif method == "PUT":
            reply = self.nam.put(req, data)
        elif method == "DELETE":
            reply = self.nam.deleteResource(req)
        else:
            reply = self.nam.post(req, data)
        reply.finished.connect(lambda r=reply: self._finish(r, ok, err))

    def _finish(self, reply, ok, err):
        body = bytes(reply.readAll())
        code = int(reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0)
        reply.deleteLater()
        js = None
        if body:
            try:
                js = json.loads(body.decode("utf-8", "replace"))
            except Exception:
                js = None
        if 200 <= code < 300:
            ok(js if js is not None else {})
            return
        detail = ""
        if isinstance(js, dict):
            detail = js.get("detail") or js.get("error") or ""
        if not detail:
            detail = reply.errorString() or f"HTTP {code}"
        if err:
            err(str(detail))
        if code == 401 and err:
            self.auth_failed.emit(str(detail))

    # ---- auth ----
    def register(self, username, password, display_name, ok, err=None):
        self._call(
            "POST", "/auth/register",
            {"username": username, "password": password, "display_name": display_name},
            lambda js: self._authed(js, ok, err), err, auth=False,
        )

    def login(self, username, password, ok, err=None):
        self._call(
            "POST", "/auth/login",
            {"username": username, "password": password},
            lambda js: self._authed(js, ok, err), err, auth=False,
        )

    def _authed(self, js, ok, err):
        tok = js.get("access_token")
        user = js.get("user")
        if tok and isinstance(user, dict):
            self.access_token = tok
            self.user = user
            self.me_id = user.get("id")
            if ok:
                ok(user)
        elif err:
            err(str(js.get("detail") or "Ошибка авторизации: пустой ответ"))

    # ---- профиль / люди ----
    def me(self, ok, err=None):
        def done(js):
            self.user = js
            self.me_id = js.get("id") if isinstance(js, dict) else self.me_id
            ok(js)
        self._call("GET", "/api/me", None, done, err)

    def users(self, ok, err=None):
        self._call("GET", "/users", None, ok, err)

    def conversations(self, ok, err=None):
        self._call("GET", "/users/conversations/me", None, ok, err)

    def dm_messages(self, other_id, ok, err=None):
        self._call("GET", f"/users/{other_id}/messages", None, ok, err)

    def update_profile(self, ok, err=None, bio=None, status=None, profile_color=None):
        payload = {}
        if bio is not None:
            payload["bio"] = bio
        if status is not None:
            payload["status"] = status
        if profile_color is not None:
            payload["profile_color"] = profile_color
        self._call("PUT", "/users/me/profile", payload, ok, err)

    def upload_avatar(self, file_path, ok, err=None):
        multi = QHttpMultiPart(QHttpMultiPart.ContentType.FormDataType, self)
        part = QHttpPart(multi)
        name = os.path.basename(file_path)
        part.setHeader(
            QNetworkRequest.KnownHeaders.ContentDispositionHeader,
            f'form-data; name="file"; filename="{name}"',
        )
        with open(file_path, "rb") as f:
            part.setBody(f.read())
        multi.append(part)
        req = QNetworkRequest(QUrl(self.base + "/users/me/avatar"))
        if self.access_token:
            req.setRawHeader(b"Authorization", b"Bearer " + self.access_token.encode())
        reply = self.nam.post(req, multi)
        reply.finished.connect(lambda r=reply: self._finish(r, ok, err))

    # ---- комнаты ----
    def rooms(self, ok, err=None):
        self._call("GET", "/rooms", None, ok, err)

    def create_room(self, name, ok, err=None):
        self._call("POST", "/rooms", {"name": name}, ok, err)

    def join_room(self, room_id, ok, err=None):
        self._call("POST", f"/rooms/{room_id}/join", {}, ok, err)

    def add_member(self, room_id, username, ok, err=None):
        self._call("POST", f"/rooms/{room_id}/members", {"username": username}, ok, err)

    def room_messages(self, room_id, ok, err=None):
        self._call("GET", f"/rooms/{room_id}/messages", None, ok, err)

    def avatar_url(self, filename):
        return f"{self.base}/avatars/{filename}"

    def health(self, ok, err=None):
        self._call("GET", "/api/health", None, ok, err, auth=False)

    def server_info(self, ok, err=None):
        self._call("GET", "/api/server-info", None, ok, err, auth=False)

    # ---------------- WS ----------------

    def ws_open(self):
        if not self.access_token:
            return
        url = QUrl(self.base.replace("http://", "ws://", 1).replace("https://", "wss://", 1) + "/ws")
        url.setQuery(f"token={self.access_token}")
        self.socket.open(url)

    def ws_close(self):
        self.socket.close()

    def ws_send(self, payload: dict):
        self.socket.sendTextMessage(json.dumps(payload, ensure_ascii=False))

    def send_room(self, room_id, content):
        self.ws_send({"type": "room_message", "room_id": room_id, "content": content})

    def send_dm(self, to_id, content):
        self.ws_send({"type": "direct_message", "to_id": to_id, "content": content})

    def send_call(self, kind, to_id=None, room_id=None, **extra):
        p = {"type": kind}
        if to_id:
            p["to_id"] = to_id
        if room_id:
            p["room_id"] = room_id
        p.update(extra)
        self.ws_send(p)

    def _on_text(self, text):
        try:
            m = json.loads(text)
        except Exception:
            return
        if not isinstance(m, dict):
            return
        t = m.get("type")
        if t == "status":
            try:
                self.ws_status.emit(int(m.get("user_id", 0)), bool(m.get("online")))
            except (TypeError, ValueError):
                pass
        elif t == "room_message":
            self.ws_room_message.emit(str(m.get("room_id", "")), m.get("message") or {})
        elif t == "direct_message":
            try:
                self.ws_dm_message.emit(
                    int(m.get("conversation_id", 0)), int(m.get("from_id", 0)), m.get("message") or {}
                )
            except (TypeError, ValueError):
                pass
        elif t == "ping":
            self.ws_send({"type": "pong"})
        elif t and (t.startswith("call") or t == "pong"):
            self.ws_call.emit(m)