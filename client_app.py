#!/usr/bin/env python3
"""nekochat Desktop — клиент с адресником серверов (стиль TeamSpeak).

Чат — нативные QWidgets (client_ui.chat), без WebEngine: сервер = API.
Запуск без аргументов открывает адресник; двойной клик — подключение.
Прямое подключение: nekochat-client --url http://host:port

Список серверов: ~/.nekochat-client/servers.json
Сессия (токены, кэш):  ~/.nekochat-client/
"""
import argparse
import json
import os
import sys
from pathlib import Path

import client_ui.theme as cli_theme

HOME = Path(os.environ.get("NEKOCHAT_CLIENT_HOME", str(Path.home() / ".nekochat-client")))
HOME.mkdir(parents=True, exist_ok=True)
SERVERS_FILE = HOME / "servers.json"
DEFAULT_URL = os.environ.get("NEKOCHAT_URL", "https://nekochat.komdu.is-cool.dev/")

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from client_ui.chat import ChatWindow


def icon() -> QIcon:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    for name in ("icon.png", "app/static/icon.png"):
        p = base / name
        if p.is_file():
            return QIcon(str(p))
    return QIcon()


# ================= адресник =================


def load_servers() -> list:
    try:
        items = json.loads(SERVERS_FILE.read_text(encoding="utf-8"))
        if isinstance(items, list):
            return [s for s in items if isinstance(s, dict) and s.get("url")]
    except Exception:
        pass
    return []


def save_servers(items: list) -> None:
    for s in items:
        s.pop("status", None)  # статус — не сохраняем, он перепроверяется
    SERVERS_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_url(url: str) -> str:
    url = url.strip()
    if url and "://" not in url:
        url = "http://" + url
    return url


class ServerDialog(QDialog):
    """Диалог «добавить / изменить сервер»: название + адрес."""

    def __init__(self, parent=None, server=None):
        super().__init__(parent)
        self.setWindowTitle("Сервер" if server else "Новый сервер")
        self.setMinimumWidth(420)
        form = QFormLayout(self)
        self.name = QLineEdit((server or {}).get("name", ""))
        self.name.setPlaceholderText("Мой сервер")
        self.url = QLineEdit((server or {}).get("url", ""))
        self.url.setPlaceholderText("https://example.com  или  http://host:8000")
        form.addRow("Название:", self.name)
        form.addRow("Адрес:", self.url)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def result_server(self, existing: dict | None = None) -> dict | None:
        url = normalize_url(self.url.text())
        if not url:
            return None
        srv = dict(existing or {})
        srv["name"] = self.name.text().strip() or url
        srv["url"] = url
        srv.setdefault("id", os.urandom(8).hex())
        return srv


class LauncherWindow(QMainWindow):
    """Адресник: список серверов + статусы + кнопки управления."""

    def __init__(self, args):
        super().__init__()
        self.args = args
        self.servers = load_servers()
        if not self.servers:  # первый запуск — публичный сервер уже в списке
            self.servers = [{"id": os.urandom(8).hex(), "name": "Nekochat", "url": DEFAULT_URL}]
            save_servers(self.servers)
        self.windows: list[ChatWindow] = []
        self.nam = QNetworkAccessManager(self)

        self.setWindowTitle("nekochat — серверы")
        self.setWindowIcon(icon())
        self.resize(560, 480)
        self.setMinimumSize(440, 340)

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(12, 12, 12, 10)
        lay.setSpacing(8)

        head = QLabel("Серверы")
        head.setStyleSheet("font-size: 16px; font-weight: bold;")
        lay.addWidget(head)

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self.connect_to)
        lay.addWidget(self.list, 1)

        btns = QHBoxLayout()
        self.connect_btn = QPushButton("Подключиться")
        self.connect_btn.setDefault(True)
        self.connect_btn.clicked.connect(
            lambda: self.connect_to(self.list.currentItem()) if self.list.currentItem() else None
        )
        add = QPushButton("Добавить…")
        add.clicked.connect(self.add_server)
        edit = QPushButton("Изменить…")
        edit.clicked.connect(self.edit_server)
        delete = QPushButton("Удалить")
        delete.clicked.connect(self.delete_server)
        refresh = QPushButton("Обновить")
        refresh.clicked.connect(self.check_all)
        for b in (self.connect_btn, add, edit, delete, refresh):
            btns.addWidget(b)
        lay.addLayout(btns)

        hint = QLabel("Двойной клик — подключиться. Свой сервер: python server.py --db data.db")
        hint.setStyleSheet("color: #777; font-size: 11px;")
        lay.addWidget(hint)

        self.setCentralWidget(central)
        self.refresh()
        self.check_all()

    # ---- список ----

    def _label(self, srv: dict) -> str:
        status = srv.get("status")
        mark = {"онлайн": "● онлайн", "офлайн": "○ офлайн"}.get(status, "…")
        return f"{srv.get('name', srv['url'])}\n{srv['url']}   {mark}"

    def refresh(self):
        self.list.clear()
        for srv in self.servers:
            item = QListWidgetItem(self._label(srv))
            item.setData(Qt.ItemDataRole.UserRole, srv)
            item.setToolTip(srv["url"])
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    # ---- статусы (GET /api/server-info) ----

    def check_all(self):
        for i in range(self.list.count()):
            self._check(self.list.item(i))

    def _check(self, item: QListWidgetItem | None):
        if item is None:
            return
        srv = item.data(Qt.ItemDataRole.UserRole)
        try:
            req = QNetworkRequest(QUrl(srv["url"].rstrip("/") + "/api/server-info"))
            reply = self.nam.get(req)
        except Exception:
            return

        def done():
            srv["status"] = "онлайн" if reply.error() == QNetworkReply.NetworkError.NoError else "офлайн"
            item.setText(self._label(srv))
            item.setData(Qt.ItemDataRole.UserRole, srv)

        def cleanup():
            # страховка по таймауту: оборвать медленный ответ и освободить reply
            if not reply.isFinished():
                reply.abort()  # вызовет finished → done()
            reply.deleteLater()

        reply.finished.connect(done)
        QTimer.singleShot(6000, cleanup)

    # ---- подключение ----

    def connect_to(self, item: QListWidgetItem | None):
        if item is None:
            return
        srv = item.data(Qt.ItemDataRole.UserRole)
        for w in self.windows:  # окно этого сервера уже открыто — поднять наверх
            if w.server.get("id") == srv.get("id"):
                w.show()
                w.raise_()
                w.activateWindow()
                return
        win = ChatWindow(srv)
        win.show()
        self.windows.append(win)

    # ---- CRUD ----

    def add_server(self):
        d = ServerDialog(self)
        if d.exec():
            srv = d.result_server()
            if srv:
                self.servers.append(srv)
                save_servers(self.servers)
                self.refresh()
                self.check_all()
            else:
                QMessageBox.warning(self, "nekochat", "Укажи адрес сервера")

    def edit_server(self):
        item = self.list.currentItem()
        if not item:
            return
        srv = item.data(Qt.ItemDataRole.UserRole)
        d = ServerDialog(self, srv)
        if d.exec():
            new = d.result_server(srv)
            if new:
                idx = self.servers.index(srv)
                self.servers[idx] = new
                save_servers(self.servers)
                self.refresh()

    def delete_server(self):
        item = self.list.currentItem()
        if not item:
            return
        srv = item.data(Qt.ItemDataRole.UserRole)
        ans = QMessageBox.question(
            self, "nekochat", f"Удалить сервер «{srv.get('name')}» из списка?"
        )
        if ans == QMessageBox.StandardButton.Yes:
            self.servers.remove(srv)
            save_servers(self.servers)
            self.refresh()


def main() -> int:
    ap = argparse.ArgumentParser(description="nekochat Desktop (нативный клиент с адресником)")
    ap.add_argument("--url", default=None,
                    help="подключиться сразу к адресу, минуя адресник")
    ap.add_argument("--width", type=int, default=1080)
    ap.add_argument("--height", type=int, default=700)
    ap.add_argument("--smoke", action="store_true",
                    help="открыть чат и проверить /api/health сервера, затем выйти")
    ap.add_argument("--debug", action="store_true", help="печать диагностики API/WS")
    args = ap.parse_args()

    _app = QApplication(sys.argv[:1])
    _app.setApplicationName("nekochat")
    _app.setWindowIcon(icon())

    # консоль Windows может быть cp1252 — кириллица в print не должна ронять клиент
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    from PySide6.QtCore import qVersion
    from PySide6 import __version__ as pyside_ver
    print(f"[nekochat] py {sys.version.split()[0]} PySide6 {pyside_ver} Qt {qVersion()}")
    print(f"[nekochat] url={args.url} smoke={args.smoke} debug={args.debug}")

    # тема по умолчанию: Material You (light, purple)
    cli_theme.apply(_app, "material", "light", "purple")

    chat: ChatWindow | None = None
    if args.url:
        chat = ChatWindow({"id": "cli", "name": "nekochat", "url": normalize_url(args.url)})
        chat.show()
    else:
        launcher = LauncherWindow(args)
        launcher.show()

    if args.smoke:
        if chat is None:  # smoke без --url: проверяем публичный адрес напрямую
            chat = ChatWindow({"id": "smoke", "name": "nekochat", "url": DEFAULT_URL})
            chat.show()

        def _ok(_js):
            print("LOADED_OK")
            QTimer.singleShot(300, _app.quit)

        def _fail(m):
            print(f"LOAD_FAILED: {m}")
            QTimer.singleShot(300, _app.quit)

        chat.api.health(_ok, _fail)
        QTimer.singleShot(90_000, lambda: (print("LOAD_TIMEOUT"), _app.quit()))

    try:
        rc = _app.exec()
    except BaseException:
        import traceback

        traceback.print_exc()
        rc = 1
    print(f"[nekochat] exec returned rc={rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())