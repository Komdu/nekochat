"""Нативное окно чата (QWidgets, без WebEngine).

Логин/регистрация, комнаты, лички, сообщения, аватарки, настройки тем
(Material You / Win98), профиль. Ходит в API через ApiClient (REST + WS).
"""
import json
import zlib
from datetime import datetime

from PySide6.QtCore import QSettings, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtNetwork import QNetworkRequest
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import you
from .api import ApiClient
from .theme import apply as apply_theme

_AV_COLORS = ["#e91e63", "#9c27b0", "#673ab7", "#3f51b5", "#2196f3",
              "#00bcd4", "#009688", "#4caf50", "#ff9800", "#f44336"]


def _stable(*parts) -> int:
    return zlib.crc32("|".join(str(p) for p in parts).encode("utf-8"))


def _user_color(user) -> QColor:
    c = (user or {}).get("profile_color")
    if c and QColor(c).isValid():
        return QColor(c)
    return QColor(_AV_COLORS[_stable((user or {}).get("username", "?")) % len(_AV_COLORS)])


def _avatar_pixmap(user, size, online=None) -> QPixmap:
    user = user or {}
    name = (user.get("display_name") or user.get("username") or "?")
    letter = (name[:1] or "?").upper()
    c = QColor(_user_color(user))
    if c.lightness() > 160:
        c = c.darker(125)
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(c)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(0, 0, size - 1, size - 1)
    f = p.font()
    f.setPixelSize(max(10, int(size * 0.52))); f.setBold(True)
    p.setFont(f)
    p.setPen(QColor("#ffffff"))
    p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, letter)
    if online is not None:
        d = max(7, int(size * 0.28))
        x, y = size - d - 1, size - d - 1
        ring = QColor("#ffffff") if c.lightness() < 140 else QColor("#27272f")
        p.setBrush(ring)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(x - 1, y - 1, d + 2, d + 2)
        p.setBrush(QColor("#31c66d") if online else QColor("#9aa0a6"))
        p.drawEllipse(x, y, d, d)
    p.end()
    return pix


def _tile_pixmap(text, color, size) -> QPixmap:
    """Скруглённый квадрат-плитка (стиль лендинга) — для комнат в сайдбаре."""
    c = QColor(color)
    if c.lightness() > 160:
        c = c.darker(125)
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(c)
    p.setPen(Qt.PenStyle.NoPen)
    r = max(3, int(size * 0.3))
    p.drawRoundedRect(0, 0, size - 1, size - 1, r, r)
    f = p.font()
    f.setPixelSize(max(9, int(size * 0.44))); f.setBold(True)
    p.setFont(f)
    p.setPen(QColor("#ffffff"))
    p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, str(text))
    p.end()
    return pix


def _round_scaled(pix, size) -> QPixmap:
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addEllipse(0, 0, size, size)
    p.setClipPath(path)
    p.drawPixmap(
        0, 0,
        pix.scaled(size, size,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation),
    )
    p.end()
    return out


def _fmt_time(s: str) -> str:
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if dt.tzinfo:
            dt = dt.astimezone()
        dt = dt.replace(tzinfo=None)
        if dt.date() == datetime.now().date():
            return dt.strftime("%H:%M")
        return dt.strftime("%d.%m %H:%M")
    except Exception:
        return ""


class AuthPage(QWidget):
    """Страница входа/регистрации (внутри окна чата)."""

    def __init__(self, api, server_name, base, on_auth):
        super().__init__()
        self.api = api
        self.on_auth = on_auth
        self.setObjectName("root")

        outer = QVBoxLayout(self)
        outer.addStretch(2)
        card = QFrame()
        card.setObjectName("card")
        card.setMaximumWidth(400)
        v = QVBoxLayout(card)
        v.setContentsMargins(28, 24, 28, 24)
        v.setSpacing(10)

        t = QLabel("Вход")
        t.setStyleSheet("font-size: 22px; font-weight: 700;")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        s = QLabel(server_name or base)
        s.setObjectName("muted")
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        s.setWordWrap(True)

        self.u = QLineEdit(); self.u.setPlaceholderText("Логин")
        self.p = QLineEdit(); self.p.setEchoMode(QLineEdit.EchoMode.Password)
        self.p.setPlaceholderText("Пароль")
        self.d = QLineEdit(); self.d.setPlaceholderText("Имя (как тебя видно другим)")
        self.d.hide()

        row = QHBoxLayout(); row.setSpacing(8)
        self.login_btn = QPushButton("Войти"); self.login_btn.setProperty("kind", "filled")
        self.reg_btn = QPushButton("Регистрация"); self.reg_btn.setProperty("kind", "tonal")
        row.addWidget(self.login_btn); row.addWidget(self.reg_btn)

        self.err = QLabel("")
        self.err.setObjectName("errLabel")
        self.err.setWordWrap(True)
        self.err.setAlignment(Qt.AlignmentFlag.AlignCenter)

        v.addWidget(t); v.addWidget(s); v.addSpacing(8)
        v.addWidget(self.u); v.addWidget(self.p); v.addWidget(self.d)
        v.addLayout(row); v.addWidget(self.err)

        outer.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(3)

        self.login_btn.clicked.connect(self._login)
        self.reg_btn.clicked.connect(self._reg)
        self.p.returnPressed.connect(self._login)
        self.u.returnPressed.connect(self._login)

    def _err(self, m):
        self.err.setText(str(m))

    def _busy(self, on):
        for w in (self.login_btn, self.reg_btn, self.u, self.p, self.d):
            w.setEnabled(not on)
        if on:
            self.err.setText("…")
        else:
            self.err.setText("")

    def _login(self):
        u = self.u.text().strip(); p = self.p.text()
        if not u or not p:
            self._err("Введи логин и пароль")
            return
        self._busy(True)
        self.api.login(u, p, self._ok, lambda m: (self._busy(False), self._err(m)))

    def _reg(self):
        u = self.u.text().strip(); p = self.p.text(); d = self.d.text().strip()
        if not u or not p or not d:
            self.d.show()
            self._err("Заполни логин, пароль и имя")
            return
        self._busy(True)
        self.api.register(u, p, d, self._ok, lambda m: (self._busy(False), self._err(m)))

    def _ok(self, user):
        self._busy(False)
        self.on_auth(user)


class ChatWindow(QMainWindow):
    """Одно окно = один сервер: вход, комнаты/ЛС, сообщения."""

    def __init__(self, server: dict):
        super().__init__()
        self.server = dict(server)
        self.base = self.server["url"].rstrip("/")
        self.name = self.server.get("name") or self.base

        self.settings = QSettings("nekochat", "nekochat")
        self.theme = str(self.settings.value("theme", "material"))
        self.mode = str(self.settings.value("mode", "light"))
        self.accent = str(self.settings.value("accent", "purple"))

        self.setWindowTitle(f"{self.name} — nekochat")
        self.resize(1080, 700)
        self.setMinimumSize(860, 560)

        self.api = ApiClient(self.base, self)
        self.api.ws_connected.connect(self._ws_connected)
        self.api.ws_status.connect(self._on_status)
        self.api.ws_room_message.connect(self._on_room_msg)
        self.api.ws_dm_message.connect(self._on_dm_msg)
        self.api.ws_error.connect(lambda m: self._err(f"WS: {m}"))
        self.api.auth_failed.connect(self._on_auth_failed)

        self.users_map: dict = {}
        self.rooms: list = []
        self.convs: list = []
        self.users: list = []
        self.current = None
        self._seen: dict = {}
        self._opt: dict = {}
        self._opt_n = 0
        self._av_cache: dict = {}
        self._loading = 0

        self._build_ui()
        apply_theme(QApplication.instance(), self.theme, self.mode, self.accent)
        self._restore_auth()

    # ---------------- UI ----------------

    def _build_ui(self):
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.auth_page = AuthPage(self.api, self.name, self.base, self._after_auth)
        self.stack.addWidget(self.auth_page)
        self.main_page = self._build_main()
        self.stack.addWidget(self.main_page)

    def _sec(self, text):
        l = QLabel(text); l.setObjectName("secLabel"); return l

    def _plus(self):
        b = QPushButton("+"); b.setProperty("kind", "icon"); b.setFixedSize(26, 26); return b

    def _build_main(self) -> QWidget:
        main = QWidget(); main.setObjectName("root")
        h = QHBoxLayout(main); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(0)

        # ---- левая панель ----
        side = QFrame(); side.setObjectName("sidePanel"); side.setFixedWidth(268)
        sv = QVBoxLayout(side); sv.setContentsMargins(10, 14, 10, 10); sv.setSpacing(6)

        top = QHBoxLayout()
        srv = QLabel(self.name); srv.setObjectName("serverName"); srv.setWordWrap(True)
        self.gear = QPushButton("⚙"); self.gear.setProperty("kind", "icon"); self.gear.setFixedSize(34, 34)
        top.addWidget(srv, 1); top.addWidget(self.gear)
        self.search = QLineEdit(); self.search.setPlaceholderText("Поиск…")
        sv.addLayout(top); sv.addWidget(self.search)

        r_head = QHBoxLayout(); r_head.setContentsMargins(0, 0, 0, 0)
        r_head.addWidget(self._sec("КОМНАТЫ")); r_head.addStretch()
        room_plus = self._plus(); r_head.addWidget(room_plus)
        self.roomList = QListWidget(); self.roomList.itemDoubleClicked.connect(self._open_item)
        self.roomList.setIconSize(QSize(30, 30))

        d_head = QHBoxLayout(); d_head.setContentsMargins(0, 0, 0, 0)
        d_head.addWidget(self._sec("ЛИЧНЫЕ")); d_head.addStretch()
        dm_plus = self._plus(); d_head.addWidget(dm_plus)
        self.dmList = QListWidget(); self.dmList.itemDoubleClicked.connect(self._open_item)
        self.dmList.setIconSize(QSize(32, 32))

        self.userList = QListWidget(); self.userList.itemDoubleClicked.connect(self._open_item)
        self.userList.setIconSize(QSize(32, 32))

        sv.addLayout(r_head); sv.addWidget(self.roomList, 1)
        sv.addLayout(d_head); sv.addWidget(self.dmList, 1)
        sv.addWidget(self._sec("ЛЮДИ")); sv.addWidget(self.userList, 1)
        self.side = side
        room_plus.clicked.connect(self.new_room_dialog)
        dm_plus.clicked.connect(self.new_dm_dialog)
        self.gear.clicked.connect(self.settings_dialog)

        # ---- правая часть ----
        right = QWidget(); right.setObjectName("root")
        rv = QVBoxLayout(right); rv.setContentsMargins(0, 0, 0, 0); rv.setSpacing(0)

        head = QWidget(); head.setObjectName("root")
        hh = QHBoxLayout(head); hh.setContentsMargins(20, 12, 16, 8)
        tcol = QVBoxLayout(); tcol.setSpacing(0)
        self.chat_title = QLabel("Добро пожаловать")
        self.chat_title.setStyleSheet("font-size: 18px; font-weight: 700;")
        self.chat_sub = QLabel(self.name); self.chat_sub.setObjectName("muted")
        tcol.addWidget(self.chat_title); tcol.addWidget(self.chat_sub)
        self.call_btn = QPushButton("📞"); self.call_btn.setProperty("kind", "tonal")
        self.call_btn.setToolTip("P2P-звонок (эксперимент)")
        hh.addLayout(tcol); hh.addStretch(); hh.addWidget(self.call_btn)

        self.msg_scroll = QScrollArea(); self.msg_scroll.setWidgetResizable(True)
        self.msg_scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget(); inner.setObjectName("root")
        self.msg_lay = QVBoxLayout(inner)
        self.msg_lay.setContentsMargins(18, 12, 18, 12); self.msg_lay.setSpacing(8)
        self.msg_lay.addStretch()
        self.msg_scroll.setWidget(inner)

        inp = QWidget(); inp.setObjectName("root")
        il = QHBoxLayout(inp); il.setContentsMargins(18, 8, 18, 14); il.setSpacing(10)
        self.msg_in = QLineEdit(); self.msg_in.setPlaceholderText("Сообщение…")
        self.send_btn = QPushButton("➤"); self.send_btn.setProperty("kind", "filled"); self.send_btn.setFixedWidth(64)
        il.addWidget(self.msg_in, 1); il.addWidget(self.send_btn)

        rv.addWidget(head); rv.addWidget(self.msg_scroll, 1); rv.addWidget(inp)

        h.addWidget(side); h.addWidget(right, 1)

        self.msg_in.returnPressed.connect(self._send)
        self.send_btn.clicked.connect(self._send)
        self.search.textChanged.connect(self._filter)
        self.call_btn.clicked.connect(self._call_info)
        return main

    # ---------------- auth ----------------

    def _restore_auth(self):
        raw = self.settings.value(f"auth/{self.base}")
        if raw:
            try:
                d = json.loads(str(raw))
                tok = d.get("access_token")
                if tok:
                    self.api.access_token = tok
                    self.api.user = d.get("user")
                    self.api.me_id = (d.get("user") or {}).get("id")
                    self.stack.setCurrentWidget(self.main_page)
                    self.load_data()

                    def validate():
                        def fail(_m):
                            if self.stack.currentWidget() is self.main_page:
                                self._force_logout("Сессия истекла — войди снова")
                        self.api.me(lambda u: None, fail)
                    QTimer.singleShot(1200, validate)
                    return
            except Exception:
                pass
        self.stack.setCurrentWidget(self.auth_page)

    def _after_auth(self, user):
        self._save_auth()
        self.stack.setCurrentWidget(self.main_page)
        self.load_data()

    def _save_auth(self):
        self.settings.setValue(f"auth/{self.base}", json.dumps(
            {"access_token": self.api.access_token, "user": self.api.user},
            ensure_ascii=False))

    def _force_logout(self, reason: str):
        self.settings.remove(f"auth/{self.base}")
        self.api.access_token = None; self.api.user = None; self.api.me_id = None
        self.api.ws_close()
        self.rooms = []; self.users = []; self.convs = []
        self.stack.setCurrentWidget(self.auth_page)
        self._err(reason)

    def _on_auth_failed(self, m):
        # 401 в середине сессии (мёртвый токен удалённого аккаунта и т.п.) —
        # не оставляем пустое главное окно, а просим войти заново.
        if self.stack.currentWidget() is self.main_page:
            self._force_logout(str(m) or "Сессия истекла — войди снова")

    def logout(self):
        self._force_logout("Вышел из аккаунта")

    # ---------------- данные ----------------

    def load_data(self):
        self._loading = 0
        for fn in (
            lambda: self.api.rooms(self._on_rooms_done, self._err),
            lambda: self.api.users(self._on_users_done, self._err),
            lambda: self.api.conversations(self._on_convs_done, self._err),
        ):
            self._loading += 1
            fn()

    def _done(self):
        self._loading -= 1
        if self._loading <= 0:
            self._populate()
            self._open_last_or_first()
            self.api.ws_open()

    def _on_rooms_done(self, js):
        self.rooms = js if isinstance(js, list) else []
        for r in self.rooms:
            for m in r.get("members") or []:
                self.users_map.setdefault(m.get("id"), m)
        self._done()

    def _on_users_done(self, js):
        self.users = [u for u in (js if isinstance(js, list) else [])
                      if u.get("id") != self.api.me_id]
        for u in self.users:
            self.users_map.setdefault(u["id"], u)
        self._done()

    def _set_convs(self, js, repop=False):
        self.convs = js if isinstance(js, list) else []
        for c in self.convs:
            u = c.get("user")
            if u:
                self.users_map.setdefault(u.get("id"), u)
        if repop:
            self._populate()

    def _on_convs_done(self, js):
        self._set_convs(js)
        self._done()

    def _refresh_convs(self):
        self.api.conversations(lambda js: self._set_convs(js, repop=True), None)

    def _populate(self):
        self.roomList.clear(); self.dmList.clear(); self.userList.clear()
        for r in self.rooms:
            name = r.get('name', '')
            it = QListWidgetItem(f"# {name}")
            it.setData(Qt.ItemDataRole.UserRole, ("room", r))
            it.setIcon(QIcon(_tile_pixmap("#", _user_color(r), 30)))
            it.setToolTip(f"{r.get('member_count') or len(r.get('members') or [])} участников")
            self.roomList.addItem(it)
        seen_dm = set()
        for c in self.convs:
            u = c.get("user") or {}
            if u.get("id") == self.api.me_id:
                continue
            seen_dm.add(u.get("id"))
            it = QListWidgetItem("")
            it.setData(Qt.ItemDataRole.UserRole, ("dm", u))
            it.setToolTip("личные сообщения")
            self.dmList.addItem(it)
        for u in self.users:
            if u.get("id") in seen_dm:
                continue
            it = QListWidgetItem("")
            it.setData(Qt.ItemDataRole.UserRole, ("dm", u))
            self.userList.addItem(it)
        self._sync_online_dots()

    def _paint_user_item(self, it):
        _, obj = it.data(Qt.ItemDataRole.UserRole)
        obj = obj or {}
        online = bool(obj.get("is_online"))
        name = obj.get("display_name") or obj.get("username") or "?"
        it.setText(name)
        it.setIcon(QIcon(_avatar_pixmap(obj, 32, online=online)))
        it.setForeground(QColor("#31c66d") if online else QColor("#9aa0a6"))

    def _sync_online_dots(self):
        for w in (self.userList, self.dmList):
            for i in range(w.count()):
                self._paint_user_item(w.item(i))

    def _open_last_or_first(self):
        last = self.settings.value(f"last/{self.base}")
        try:
            d = json.loads(str(last)) if last else None
        except Exception:
            d = None
        if d and d.get("kind") == "room":
            for r in self.rooms:
                if str(r.get("id")) == str(d.get("id")):
                    self.open_room(r); return
        if d and d.get("kind") == "dm":
            for u in self.users:
                if u.get("id") == d.get("id"):
                    self.open_dm(u); return
            for c in self.convs:
                if (c.get("user") or {}).get("id") == d.get("id"):
                    self.open_dm(c.get("user")); return
        if self.rooms:
            self.open_room(self.rooms[0])

    # ---------------- навигация ----------------

    def _open_item(self, item):
        kind, obj = item.data(Qt.ItemDataRole.UserRole)
        if kind == "room":
            self.open_room(obj)
        else:
            self.open_dm(obj)

    def cur_key(self):
        return self.current["key"] if self.current else None

    def open_room(self, r):
        rid = str(r.get("id"))
        key = ("room", rid)
        self.current = {"kind": "room", "id": rid, "key": key, "label": f"# {r.get('name', '')}"}
        self.chat_title.setText(self.current["label"])
        n = r.get("member_count") or len(r.get("members") or [])
        self.chat_sub.setText(f"{n} участников")
        self.settings.setValue(f"last/{self.base}", json.dumps({"kind": "room", "id": rid}))
        self._open_history(key, lambda ok: self.api.room_messages(int(rid), ok, self._err))

    def open_dm(self, u):
        uid = str(u.get("id"))
        key = ("dm", uid)
        self.current = {"kind": "dm", "id": uid, "key": key,
                        "label": f"@ {u.get('display_name') or u.get('username') or uid}"}
        self.users_map.setdefault(u.get("id"), u)
        self.chat_title.setText(self.current["label"])
        self.chat_sub.setText("личные сообщения")
        self.settings.setValue(f"last/{self.base}", json.dumps({"kind": "dm", "id": u.get("id")}))
        self._open_history(key, lambda ok: self.api.dm_messages(int(u.get("id")), ok, self._err))

    def _open_history(self, key, fetcher):
        self._seen.setdefault(key, set())
        self.clear_msgs()
        fetcher(lambda msgs: self._seed_history(key, msgs))

    def clear_msgs(self):
        while self.msg_lay.count() > 1:
            it = self.msg_lay.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()

    def _seed_history(self, key, msgs):
        s = self._seen.setdefault(key, set())
        for m in msgs or []:
            mid = m.get("id")
            if mid is not None:
                s.add(mid)
            self._bubble(key, m)
        self._scroll_bottom()

    # ---------------- сообщения ----------------

    def _send(self):
        if not self.current:
            return
        text = self.msg_in.text().strip()
        if not text:
            return
        self.msg_in.setText("")
        key = self.current["key"]
        self._opt_n += 1
        local = f"opt:{self._opt_n}"
        stamp = datetime.now().isoformat()
        if key[0] == "room":
            self.api.send_room(int(self.current["id"]), text)
            msg = {"id": local, "content": text, "created_at": stamp, "user_id": self.api.me_id}
        else:
            self.api.send_dm(int(self.current["id"]), text)
            msg = {"id": local, "content": text, "created_at": stamp, "sender_id": self.api.me_id}
        self._opt.setdefault(key, []).append({"id": local, "content": text})
        self._bubble(key, msg)
        self._scroll_bottom()

    def _bubble(self, key, msg):
        content = str(msg.get("content") or "")
        if not content.strip():
            return
        mine = False
        sender = None
        if key and key[0] == "room":
            uid = msg.get("user_id")
            mine = uid == self.api.me_id
            sender = self.users_map.get(uid) or {"id": uid, "display_name": f"@{uid}", "username": ""}
        else:
            sid = msg.get("sender_id")
            mine = sid == self.api.me_id
            send = msg.get("sender")
            if isinstance(send, dict):
                sender = send
                self.users_map.setdefault(send.get("id"), send)
            else:
                sender = self.users_map.get(sid) or {"id": sid, "display_name": f"@{sid}", "username": ""}
        w = self._make_bubble(content, sender, mine, msg.get("created_at", ""))
        align = Qt.AlignmentFlag.AlignRight if mine else Qt.AlignmentFlag.AlignLeft
        self.msg_lay.insertWidget(max(1, self.msg_lay.count() - 1), w, 0, align)

    def _make_bubble(self, content, sender, mine, created):
        frame = QFrame()
        frame.setProperty("bubble", "mine" if mine else "other")
        frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        row = QHBoxLayout(frame); row.setContentsMargins(12, 8, 12, 8); row.setSpacing(10)
        av = QLabel(); av.setFixedSize(34, 34); av.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_avatar(av, sender, 34)
        col = QVBoxLayout(); col.setSpacing(2)
        head = QHBoxLayout(); head.setSpacing(8)
        nm = QLabel(sender.get("display_name") or sender.get("username") or "?")
        nm.setObjectName("msgName")
        tm = QLabel(_fmt_time(created)); tm.setObjectName("time")
        head.addWidget(nm); head.addStretch(); head.addWidget(tm)
        txt = QLabel(content); txt.setObjectName("msgText")
        txt.setWordWrap(True)
        txt.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        txt.setMaximumWidth(560)
        col.addLayout(head); col.addWidget(txt)
        row.addWidget(av); row.addLayout(col, 1)
        return frame

    def _consume_opt(self, key, msg) -> bool:
        content = msg.get("content") or ""
        if key[0] == "room" and msg.get("user_id") != self.api.me_id:
            return False
        if key[0] == "dm" and msg.get("sender_id") != self.api.me_id:
            return False
        lst = self._opt.get(key)
        if lst:
            for i, rec in enumerate(lst):
                if rec["content"] == content:
                    del lst[i]
                    return True
        return False

    def _on_room_msg(self, room_id, msg):
        key = ("room", str(room_id))
        s = self._seen.setdefault(key, set())
        mid = msg.get("id")
        if mid is not None:
            if mid in s:
                return
            s.add(mid)
        if self.cur_key() == key and self._consume_opt(key, msg):
            return
        if self.cur_key() == key:
            self._bubble(key, msg)
            self._scroll_bottom()

    def _on_dm_msg(self, conv_id, from_id, msg):
        key = ("dm", str(from_id))
        s = self._seen.setdefault(key, set())
        mid = msg.get("id")
        if mid is not None:
            if mid in s:
                return
            s.add(mid)
        if self.cur_key() == key and self._consume_opt(key, msg):
            return
        if self.cur_key() == key:
            self._bubble(key, msg)
            self._scroll_bottom()
        else:
            self._refresh_convs()

    def _on_status(self, uid, online):
        if uid in self.users_map and isinstance(self.users_map[uid], dict):
            self.users_map[uid]["is_online"] = online
        if self.api.me_id is not None and uid == self.api.me_id:
            return
        for w in (self.userList, self.dmList):
            for i in range(w.count()):
                it = w.item(i)
                _, obj = it.data(Qt.ItemDataRole.UserRole)
                if obj and obj.get("id") == uid:
                    self._paint_user_item(it)

    # ---------------- аватары ----------------

    def _set_avatar(self, label, user, size):
        user = user or {}
        filename = user.get("avatar")
        cached = self._av_cache.get(filename) if filename else None
        if cached is not None:
            label.setPixmap(cached)
            return
        label.setPixmap(_avatar_pixmap(user, size))
        if filename:
            self._fetch_avatar(filename, size, label)

    def _fetch_avatar(self, filename, size, label):
        req = QNetworkRequest(QUrl(self.api.avatar_url(filename)))
        reply = self.api.nam.get(req)

        def done():
            data = bytes(reply.readAll())
            reply.deleteLater()
            if not data:
                return
            pm = QPixmap()
            if not pm.loadFromData(data) or pm.isNull():
                return
            pix = _round_scaled(pm, size)
            self._av_cache[filename] = pix
            try:
                label.setPixmap(pix)
            except RuntimeError:
                pass
        reply.finished.connect(done)

    # ---------------- диалоги ----------------

    def settings_dialog(self):
        SettingsDialog(self).exec()

    def new_room_dialog(self):
        d = QDialog(self); d.setWindowTitle("Новая комната")
        v = QVBoxLayout(d); v.setContentsMargins(20, 18, 20, 16)
        v.addWidget(QLabel("Название комнаты"))
        e = QLineEdit(); e.setPlaceholderText("например: общий")
        v.addWidget(e)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, d)
        bb.accepted.connect(d.accept); bb.rejected.connect(d.reject)
        v.addWidget(bb)
        if d.exec() and e.text().strip():
            self.api.create_room(e.text().strip(), self._room_created, self._err)

    def _room_created(self, r):
        self.rooms.append(r)
        for m in r.get("members") or []:
            self.users_map.setdefault(m.get("id"), m)
        self._populate()
        self.open_room(r)

    def new_dm_dialog(self):
        d = QDialog(self); d.setWindowTitle("Личные сообщения")
        v = QVBoxLayout(d); v.setContentsMargins(20, 18, 20, 16)
        lst = QListWidget()
        lst.setIconSize(QSize(28, 28))
        for u in self.users:
            if u.get("id") == self.api.me_id:
                continue
            it = QListWidgetItem(u.get("display_name") or u.get("username") or str(u.get("id")))
            it.setData(Qt.ItemDataRole.UserRole, u)
            it.setIcon(QIcon(_avatar_pixmap(u, 28)))
            lst.addItem(it)
        lst.itemDoubleClicked.connect(
            lambda it, dd=d: (self.open_dm(it.data(Qt.ItemDataRole.UserRole)), dd.accept()))
        v.addWidget(lst)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, d)
        bb.rejected.connect(d.reject)
        v.addWidget(bb)
        d.resize(320, 360)
        d.exec()

    def _call_info(self):
        QMessageBox.information(
            self, "Звонки",
            "Нативный P2P-звонок — следующий эксперимент.\n"
            "Пока в этой сборке звонки не подключены.")

    def _filter(self, text):
        t = text.strip().lower()
        for w in (self.roomList, self.dmList, self.userList):
            for i in range(w.count()):
                w.item(i).setHidden(bool(t) and t not in w.item(i).text().lower())

    # ---------------- сокеты / утилиты ----------------

    def _ws_connected(self):
        self._err("подключено (WS)")

    def _err(self, m):
        try:
            self.statusBar().showMessage(str(m), 6000)
        except Exception:
            pass

    def _scroll_bottom(self):
        QTimer.singleShot(0, self._do_scroll)

    def _do_scroll(self):
        try:
            sb = self.msg_scroll.verticalScrollBar()
            sb.setValue(sb.maximum())
        except RuntimeError:
            pass

    def save_theme(self):
        self.settings.setValue("theme", self.theme)
        self.settings.setValue("mode", self.mode)
        self.settings.setValue("accent", self.accent)

    def closeEvent(self, event):
        try:
            print(f"[nekochat] ChatWindow close url={self.base}")
        except Exception:
            pass
        self.api.ws_close()
        super().closeEvent(event)


class SettingsDialog(QDialog):
    """Тема (Material You / Win98), режим, акцент — применяется сразу."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.accent = win.accent
        self.setWindowTitle("Настройки")
        v = QVBoxLayout(self); v.setContentsMargins(22, 18, 22, 16); v.setSpacing(8)

        v.addWidget(QLabel("Тема"))
        self.rb_m = QRadioButton("Material You"); self.rb_w = QRadioButton("Win98")
        h = QHBoxLayout(); h.addWidget(self.rb_m); h.addWidget(self.rb_w); h.addStretch()
        v.addLayout(h)

        v.addWidget(QLabel("Режим (Material You)"))
        self.rb_l = QRadioButton("Светлая"); self.rb_d = QRadioButton("Тёмная")
        self.mode_grp = QButtonGroup(self)
        self.mode_grp.addButton(self.rb_l); self.mode_grp.addButton(self.rb_d)
        h2 = QHBoxLayout(); h2.addWidget(self.rb_l); h2.addWidget(self.rb_d); h2.addStretch()
        v.addLayout(h2)

        v.addWidget(QLabel("Акцент (Material You)"))
        sw = QHBoxLayout(); sw.setSpacing(6)
        self._swatches = {}
        grp = QButtonGroup(self); grp.setExclusive(True)
        for name, col in you.PRESETS.items():
            b = QPushButton(); b.setCheckable(True); b.setFixedSize(30, 30)
            b.setToolTip(name)
            b.setStyleSheet(
                f"QPushButton {{ background: {col}; border: 2px solid transparent; border-radius: 15px; }}"
                f"QPushButton:checked {{ border: 3px solid #3f3f43; }}"
            )
            b.clicked.connect(lambda _c=False, n=name: self._pick(n))
            grp.addButton(b); self._swatches[name] = b
            sw.addWidget(b)
        self.custom_btn = QPushButton("Свой…"); self.custom_btn.setProperty("kind", "tonal")
        self.custom_btn.clicked.connect(self._custom)
        sw.addWidget(self.custom_btn); sw.addStretch()
        v.addLayout(sw)

        for rb in (self.rb_m, self.rb_w, self.rb_l, self.rb_d):
            rb.toggled.connect(self._apply)

        row = QHBoxLayout()
        logout = QPushButton("Выйти из аккаунта"); logout.setProperty("kind", "text")
        logout.clicked.connect(self._logout)
        close = QPushButton("Закрыть"); close.setProperty("kind", "filled")
        close.clicked.connect(self.close)
        row.addWidget(logout); row.addStretch(); row.addWidget(close)
        v.addLayout(row)
        self._reflect()

    def _reflect(self):
        self.rb_m.setChecked(self.win.theme == "material")
        self.rb_w.setChecked(self.win.theme == "win98")
        self.rb_l.setChecked(self.win.mode != "dark")
        self.rb_d.setChecked(self.win.mode == "dark")
        for name, b in self._swatches.items():
            b.setChecked(you.hex_for(self.accent) == you.PRESETS[name])
        self.rb_l.setEnabled(self.win.theme == "material")
        self.rb_d.setEnabled(self.win.theme == "material")

    def _pick(self, name):
        self.accent = name
        self._apply()

    def _custom(self):
        cur = self.accent if QColor(self.accent).isValid() else "#6750a4"
        c = QColorDialog.getColor(QColor(cur), self, "Цвет акцента")
        if c.isValid():
            self.accent = c.name()
            self._apply()

    def _apply(self):
        theme = "material" if self.rb_m.isChecked() else "win98"
        mode = "dark" if self.rb_d.isChecked() else "light"
        self.rb_l.setEnabled(theme == "material")
        self.rb_d.setEnabled(theme == "material")
        self.win.accent = self.accent
        self.win.theme = theme
        self.win.mode = mode
        self.win.save_theme()
        apply_theme(QApplication.instance(), theme, mode, self.accent)

    def _logout(self):
        self.win.logout()
        self.accept()


class ProfileDialog(QDialog):
    """Статус, био, цвет профиля, аватар."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.api = win.api
        self.color = (self.api.user or {}).get("profile_color")
        u = self.api.user or {}
        self.setWindowTitle("Профиль")
        v = QVBoxLayout(self); v.setContentsMargins(22, 20, 22, 16); v.setSpacing(10)

        head = QHBoxLayout(); head.setSpacing(14)
        self.av = QLabel(); self.av.setFixedSize(84, 84); self.av.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col = QVBoxLayout(); col.setSpacing(2)
        nm = QLabel(u.get("display_name") or u.get("username") or "?")
        nm.setStyleSheet("font-size: 17px; font-weight: 700;")
        un = QLabel("@" + (u.get("username") or "")); un.setObjectName("muted")
        ch = QPushButton("Сменить аватар"); ch.setProperty("kind", "tonal")
        ch.clicked.connect(self._avatar)
        col.addWidget(nm); col.addWidget(un); col.addWidget(ch)
        head.addWidget(self.av); head.addLayout(col)
        v.addLayout(head)

        self.status = QLineEdit(u.get("status") or ""); self.status.setPlaceholderText("Статус")
        self.bio = QPlainTextEdit(u.get("bio") or ""); self.bio.setPlaceholderText("О себе")
        self.bio.setMaximumHeight(90)
        v.addWidget(self.status); v.addWidget(self.bio)

        crow = QHBoxLayout()
        crow.addWidget(QLabel("Цвет профиля:"))
        self.color_btn = QPushButton(); self.color_btn.setFixedSize(30, 30)
        self.color_btn.clicked.connect(self._color)
        crow.addWidget(self.color_btn); crow.addStretch()
        v.addLayout(crow)
        self._set_color_btn(self.color)

        row = QHBoxLayout()
        save = QPushButton("Сохранить"); save.setProperty("kind", "filled"); save.clicked.connect(self._save)
        close = QPushButton("Закрыть"); close.setProperty("kind", "text"); close.clicked.connect(self.close)
        row.addWidget(save); row.addStretch(); row.addWidget(close)
        v.addLayout(row)

    def _set_color_btn(self, color):
        if not color or not QColor(color).isValid():
            color = "#bbbbbb"
        self.color_btn.setStyleSheet(
            f"QPushButton {{ background: {color}; border-radius: 15px; border: 1px solid #666; }}")

    def _color(self):
        cur = self.color if self.color and QColor(self.color).isValid() else "#6750a4"
        c = QColorDialog.getColor(QColor(cur), self, "Цвет профиля")
        if c.isValid():
            self.color = c.name()
            self._set_color_btn(self.color)

    def _avatar(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Аватар", "", "Изображения (*.png *.jpg *.jpeg *.webp *.gif)")
        if not path:
            return
        self.api.upload_avatar(path, self._avatar_done, self.win._err)

    def _avatar_done(self, u):
        self.api.user = u
        self.win._save_auth()
        self.win._set_avatar(self.av, u, 84)
        self.win._populate()

    def _save(self):
        payload = {
            "status": self.status.text().strip() or None,
            "bio": self.bio.toPlainText().strip() or None,
            "profile_color": self.color or None,
        }

        def done(u):
            self.api.user = u
            self.win._save_auth()
            self.win._populate()

        self.api.update_profile(done, self.win._err, **payload)