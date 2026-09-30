"""Идентификация клиента по заголовку.

Формат заголовка (пример):
    X-Neko-Client: nekochat-web/0.11.0 (windows; chromium) build=3691612

Что здесь есть и чего нет.

Значение приходит ОТ КЛИЕНТА, то есть от того, кого мы хотим опознать. Поэтому
проверить по нему, «свой» ли это клиент, нельзя: кто угодно читает исходники
(они лежат в браузере) и подставляет что хочет. Встроенный в клиент «сертификат»
секретом не является по той же причине.

Что заголовок РЕАЛЬНО даёт:
  - чек версии: можно сказать «у тебя устаревшая версия» вместо загадочных
    поломок на новом сервере;
  - видимость, чем именно человек сидит (веб, телефон, другой клиент);
  - статистику: чем люди пользуются, где ломается.

Поэтому строгий режим (обязательный заголовок) по умолчанию ВЫКЛЮЧЕН: он роняет
curl, скрипты, health-чеки и любой сторонний код, а выигрыш даёт нулевой —
подделать заголовок так же легко, как его послать. Включается флагом
client_header_strict, когда понадобится.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

HEADER = "X-Neko-Client"
# WebSocket не даёт добавить заголовки из браузера, поэтому для сокетов то же
# самое едет параметром в URL
WS_PARAM = "c"

# "имя/версия (ос; движок) build=метка client=метка_клиента"
# ВАЖНО: клиент шлёт ровно это значение (web/src/lib/ident.ts). Если формат
# разойдётся, разбор молча свалится в запасной путь и имя клиента будет
# обрезано — поэтому здесь новое поле добавляется вместе с тем, что его
# отправляет, а не отдельно.
_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9_.+-]{1,32})"
    r"(?:/(?P<version>[0-9A-Za-z.+-]{1,32}))?"
    r"(?:\s*\((?P<os>[^;()]{0,40})(?:;\s*(?P<engine>[^()]{0,40}))?\))?"
    r"(?:\s+build=(?P<build>[0-9a-zA-Z._-]{1,64}))?"
    r"(?:\s+client=(?P<client>[0-9a-zA-Z._-]{0,64}))?"
    r"\s*$"
)

# Наши клиенты: имя -> (иконка, человекочитаемое имя)
KNOWN_CLIENTS: dict[str, tuple[str, str]] = {
    "nekochat-web": ("web", "Веб-клиент"),
    "nekochat-pwa": ("web", "Веб-клиент"),
    "nekochat-desktop": ("desktop", "Десктоп"),
    "nekochat-serve": ("terminal", "Консольный клиент"),
}

UNKNOWN_ICON = "unknown"


@dataclass(frozen=True)
class ClientInfo:
    """Что удалось вытащить из заголовка. raw сохраняем целиком — по нему
    видно, что прислал клиент, даже если формат поехал."""

    name: str = ""
    version: str = ""
    os: str = ""
    engine: str = ""
    build: str = ""
    client: str = ""
    raw: str = ""
    known: bool = False
    icon: str = UNKNOWN_ICON

    @property
    def label(self) -> str:
        """Что показать человеку: «Веб-клиент 0.11.0»."""
        if not self.name:
            return ""
        base = KNOWN_CLIENTS.get(self.name, (UNKNOWN_ICON, self.name))[1]
        return f"{base} {self.version}".strip()

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "os": self.os,
            "engine": self.engine,
            "build": self.build,
            "client": self.client,
            "icon": self.icon,
            "known": self.known,
            "label": self.label,
        }


EMPTY = ClientInfo()


def parse(value: str | None) -> ClientInfo:
    """Разобрать заголовок. Мусор не роняем, а помечаем как неизвестный."""
    if not value:
        return EMPTY
    raw = value.strip()
    m = _RE.match(raw)
    if not m:
        # не выкидываем: возможно это будущий формат, покажем как есть
        return ClientInfo(name=raw[:32], raw=raw, known=False, icon=UNKNOWN_ICON)
    name = m.group("name") or ""
    icon, _ = KNOWN_CLIENTS.get(name, (UNKNOWN_ICON, name))
    os_part = (m.group("os") or "").strip()
    engine = (m.group("engine") or "").strip()
    # движок часто сидит в os через точку с запятой: "windows; chromium"
    if ";" in os_part:
        os_part, engine2 = os_part.split(";", 1)
        engine = engine or engine2.strip()
    return ClientInfo(
        name=name,
        version=m.group("version") or "",
        os=os_part.strip(),
        engine=engine,
        build=m.group("build") or "",
        client=m.group("client") or "",
        raw=raw,
        known=name in KNOWN_CLIENTS,
        icon=icon,
    )


@dataclass
class ClientStats:
    """Счётчики: сколько раз пришёл каждый клиент и сколько раз без
    заголовка. Сбрасываются при перезапуске процесса."""

    seen: dict[str, int] = field(default_factory=dict)
    missing: int = 0
    rejected: int = 0
    last_raw: str = ""

    def note(self, info: ClientInfo) -> None:
        if not info.name:
            self.missing += 1
            return
        key = f"{info.name}/{info.version}" if info.version else info.name
        self.seen[key] = self.seen.get(key, 0) + 1
        self.last_raw = info.raw

    def as_dict(self) -> dict:
        return {"seen": dict(sorted(self.seen.items(), key=lambda kv: -kv[1])),
                "missing": self.missing, "rejected": self.rejected, "last": self.last_raw}


stats = ClientStats()
