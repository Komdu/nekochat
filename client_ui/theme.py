"""Темы нативного клиента: Material You (дин. M3-палитра) и Win98 (QSS).

`apply(app, theme, mode, accent)` перекрашивает всё приложение на лету.
accent: имя пресета или '#rrggbb'; 'purple'/'None' — стоковая палитра M3.
"""
from PySide6.QtGui import QColor

from . import you

# ---- стоковая палитра M3 (purple) — как базовые css-переменные веб-версии ----
_STOCK = {
    True: {  # dark
        "primary": "#d0bcff", "on_primary": "#371e73",
        "primary_container": "#4f378b", "on_primary_container": "#eaddff",
        "secondary": "#ccc2dc", "on_secondary": "#322e3e",
        "secondary_container": "#4a4458", "on_secondary_container": "#e8def8",
        "surface": "#141218", "on_surface": "#e6e0e9",
        "on_surface_variant": "#cac4d0", "outline": "#938f99",
        "outline_variant": "#49454f",
        "surface_lowest": "#0f0d13", "surface_low": "#1d1b22",
        "surface_container": "#211f26", "surface_high": "#2b2930",
        "surface_highest": "#36343b",
    },
    False: {  # light
        "primary": "#6750a4", "on_primary": "#ffffff",
        "primary_container": "#eaddff", "on_primary_container": "#21005d",
        "secondary": "#625b71", "on_secondary": "#ffffff",
        "secondary_container": "#e8def8", "on_secondary_container": "#1d192b",
        "surface": "#fffbfe", "on_surface": "#1c1b1f",
        "on_surface_variant": "#49454f", "outline": "#79747e",
        "outline_variant": "#cac4d0",
        "surface_lowest": "#ffffff", "surface_low": "#f7f2fa",
        "surface_container": "#fffbfe", "surface_high": "#ece6f0",
        "surface_highest": "#e6e0e9",
    },
}


def _page_vars(base: dict) -> dict:
    """Страничные токены от стоковой базы (для QSS)."""
    return {
        "title1": base["primary"],
        "title2": base["on_surface_variant"],
        "focus": base["primary_container"],
        "link": base["primary"],
        "mine": base["primary_container"],
        "mine_sender": base["on_primary_container"],
        "chat_sub": base["on_surface_variant"],
        "desk": base["surface_lowest"],
        "panel": base["surface_low"],
        "panel_hover": base["surface_high"],
        "divider": base["outline_variant"],
        "text1": base["on_surface"],
        "muted": base["on_surface_variant"],
    }


def _mix(c1, c2, k: float) -> str:
    """Линейная смесь двух цветов; k=0 → c1, k=1 → c2."""
    r = round(c1.red() * (1 - k) + c2.red() * k)
    g = round(c1.green() * (1 - k) + c2.green() * k)
    b = round(c1.blue() * (1 - k) + c2.blue() * k)
    return "#%02x%02x%02x" % (r, g, b)


def _lift_dark(base: dict) -> dict:
    """Тёмные акценты (например indigo #283593) дают поверхности почти-чёрными
    (#000102): такой UI не читается. Подмешиваем нейтральную тёмную базу M3,
    чтобы оставить лёгкий оттенок акцента, но гарантировать видимость."""
    out = dict(base)
    st = _STOCK[True]
    for key, neutral in (
        ("surface_lowest", st["surface_lowest"]),
        ("surface_low", st["surface_low"]),
        ("surface", st["surface"]),
        ("surface_high", st["surface_high"]),
        ("surface_highest", st["surface_highest"]),
        ("outline_variant", st["outline_variant"]),
    ):
        if key in out:
            out[key] = _mix(QColor(out[key]), QColor(neutral), 0.75)
    return out


def m3_tokens(accent, dark: bool) -> dict:
    if accent and str(accent).lower() not in ("", "purple", "default"):
        t = you.tokens(you.hex_for(str(accent)), dark)
        base = {
            "primary": t["md-sys-color-primary"],
            "on_primary": t["md-sys-color-on-primary"],
            "primary_container": t["md-sys-color-primary-container"],
            "on_primary_container": t["md-sys-color-on-primary-container"],
            "secondary": t["md-sys-color-secondary"],
            "on_secondary": t["md-sys-color-on-secondary"],
            "secondary_container": t["md-sys-color-secondary-container"],
            "on_secondary_container": t["md-sys-color-on-secondary-container"],
            "surface": t["md-sys-color-surface"],
            "on_surface": t["md-sys-color-on-surface"],
            "on_surface_variant": t["md-sys-color-on-surface-variant"],
            "outline": t["md-sys-color-outline"],
            "outline_variant": t["md-sys-color-outline-variant"],
            "surface_lowest": t["md-sys-color-surface-container-lowest"],
            "surface_low": t["md-sys-color-surface-container-low"],
            "surface": t["md-sys-color-surface-container"],
            "surface_high": t["md-sys-color-surface-container-high"],
            "surface_highest": t["md-sys-color-surface-container-highest"],
        }
    else:
        base = dict(_STOCK[bool(dark)])
    if dark:
        base = _lift_dark(base)
    return {**base, **_page_vars(base)}


def material_qss(accent, dark: bool) -> str:
    c = m3_tokens(accent, dark)
    font = "'Roboto', 'Segoe UI', sans-serif"
    return f"""
* {{ font-family: {font}; }}
QMainWindow, QDialog {{ background: {c['desk']}; color: {c['text1']}; }}
QWidget {{ color: {c['text1']}; }}
#root {{ background: {c['desk']}; }}

/* --- боковая панель --- */
#sidePanel {{
    background: {c['panel']};
    border: none;
    border-top-right-radius: 24px;
    border-bottom-right-radius: 24px;
}}
#secLabel {{
    color: {c['muted']};
    font-size: 11px; font-weight: 700; letter-spacing: 1px;
    padding: 10px 12px 4px 12px;
}}
#serverName {{ color: {c['title1']}; font-size: 15px; font-weight: 700; }}

/* --- списки --- */
QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item {{
    border-radius: 12px; padding: 8px 12px; color: {c['text1']};
}}
QListWidget::item:hover {{ background: {c['panel_hover']}; }}
QListWidget::item:selected {{
    background: {c['primary_container']}; color: {c['on_primary_container']};
}}

/* --- кнопки --- */
QPushButton {{ border: none; border-radius: 999px; padding: 9px 20px; font-weight: 600; }}
QPushButton[kind="filled"] {{ background: {c['primary']}; color: {c['on_primary']}; }}
QPushButton[kind="tonal"] {{ background: {c['secondary_container']}; color: {c['on_secondary_container']}; }}
QPushButton[kind="text"] {{ background: transparent; color: {c['primary']}; }}
QPushButton[kind="icon"] {{ background: transparent; border-radius: 999px; padding: 8px; font-size: 18px; }}
QPushButton[kind="icon"]:hover {{ background: {c['panel_hover']}; }}
QPushButton:disabled {{ color: {c['muted']}; background: {c['surface_highest']}; }}

/* --- поля --- */
QLineEdit, QTextEdit {{
    background: {c['surface_lowest']}; color: {c['text1']};
    border: 1px solid {c['outline']}; border-radius: 12px; padding: 8px 12px;
    selection-background-color: {c['primary']}; selection-color: {c['on_primary']};
}}
QLineEdit:focus, QTextEdit:focus {{ border: 2px solid {c['primary']}; padding: 7px 11px; }}
QLineEdit:disabled {{ color: {c['muted']}; background: {c['panel']}; }}
QComboBox {{
    background: {c['surface_lowest']}; color: {c['text1']};
    border: 1px solid {c['outline']}; border-radius: 12px; padding: 7px 12px;
}}
QComboBox QAbstractItemView {{
    background: {c['surface_high']}; color: {c['text1']};
    selection-background-color: {c['primary_container']};
    selection-color: {c['on_primary_container']};
    border-radius: 12px;
}}

/* --- сообщения --- */
QFrame[bubble="mine"] {{
    background: {c['mine']}; color: {c['mine_sender']};
    border-radius: 16px;
}}
QFrame[bubble="other"] {{
    background: {c['surface_high']}; color: {c['text1']};
    border-radius: 16px;
}}
QFrame[bubble="sys"] {{ background: transparent; }}
QFrame[bubble="mine"] QLabel {{ color: {c['mine_sender']}; }}
QFrame[bubble="other"] QLabel {{ color: {c['text1']}; }}
QFrame[bubble] QLabel#msgName {{ font-weight: 700; }}
QFrame[bubble] QLabel#time {{ color: {c['chat_sub']}; font-size: 11px; }}

/* --- карточки / диалоги --- */
#card {{
    background: {c['panel']};
    border: 1px solid {c['divider']};
    border-radius: 24px;
}}
QMessageBox {{ background: {c['panel']}; }}

/* --- скроллбары --- */
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {c['surface_highest']}; border-radius: 5px; min-height: 30px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: transparent; height: 10px; margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {c['surface_highest']}; border-radius: 5px; min-width: 30px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* --- прочее --- */
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
#errLabel {{ color: {c['link']}; }}
#muted {{ color: {c['muted']}; }}
#time {{ color: {c['chat_sub']}; font-size: 11px; }}
#spacer {{ }}
QToolTip {{
    background: {c['surface_highest']}; color: {c['text1']};
    border: 1px solid {c['outline']}; border-radius: 8px; padding: 6px 10px;
}}
QMenu {{
    background: {c['panel']}; color: {c['text1']}; border: 1px solid {c['divider']};
    border-radius: 12px; padding: 6px;
}}
QMenu::item:selected {{ background: {c['primary_container']}; color: {c['on_primary_container']}; border-radius: 8px; }}
QCheckBox, QRadioButton {{ color: {c['text1']}; }}
QSlider::groove:horizontal {{ height: 4px; background: {c['surface_highest']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 18px; background: {c['primary']}; border-radius: 9px; margin: -7px 0; }}
"""


def win98_qss() -> str:
    font = "'Tahoma', 'Segoe UI', sans-serif"
    return f"""
* {{ font-family: {font}; font-size: 12px; }}
QMainWindow, QDialog, QWidget {{ background: #c0c0c0; color: #000000; }}
#root {{ background: #008080; }}  /* рабочий стол teal */
#sidePanel {{ background: #c0c0c0; border: 2px inset #808080; }}
#secLabel {{ color: #000080; font-weight: bold; padding: 2px 6px; }}
#serverName {{ color: #000080; font-weight: bold; font-size: 14px; }}

QPushButton {{
    background: #d4d0c8;
    border: 2px solid;
    border-top-color: #ffffff; border-left-color: #ffffff;
    border-bottom-color: #404040; border-right-color: #404040;
    padding: 5px 14px; font-weight: bold;
}}
QPushButton:pressed {{
    border-top-color: #404040; border-left-color: #404040;
    border-bottom-color: #ffffff; border-right-color: #ffffff;
}}
QPushButton:disabled {{ color: #808080; }}
QPushButton[kind="icon"] {{ padding: 4px; }}

QLineEdit, QTextEdit {{ background: #ffffff; border: 2px inset #808080; padding: 3px 5px; }}
QComboBox {{ background: #d4d0c8; border: 2px inset #808080; padding: 3px; }}

QListWidget {{ background: #ffffff; border: 2px inset #808080; }}
QListWidget::item {{ padding: 3px 6px; }}
QListWidget::item:selected {{ background: #000080; color: #ffffff; }}

QScrollBar:vertical {{ background: #c0c0c0; width: 16px; border: none; }}
QScrollBar::handle:vertical {{
    background: #d4d0c8; border: 2px solid;
    border-top-color: #ffffff; border-left-color: #ffffff;
    border-bottom-color: #404040; border-right-color: #404040;
    min-height: 20px; margin: 0;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    background: #d4d0c8; height: 16px;
    border: 2px solid;
    border-top-color: #ffffff; border-left-color: #ffffff;
    border-bottom-color: #404040; border-right-color: #404040;
}}
QFrame[bubble="mine"], QFrame[bubble="other"] {{ background: #ffffc1; border: 1px solid #808080; }}
QFrame[bubble="sys"] {{ background: transparent; }}
QFrame[bubble] QLabel {{ color: #000000; }}
QFrame[bubble] QLabel#msgName {{ font-weight: 700; }}
QFrame[bubble] QLabel#time {{ color: #555555; font-size: 11px; }}
#card {{ background: #c0c0c0; border: 2px outset #ffffff; }}
#errLabel {{ color: #800000; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QToolTip {{ background: #ffffe1; color: #000000; border: 1px solid #000000; }}
QMenu {{ background: #ffffff; border: 1px solid #000000; }}
QMenu::item:selected {{ background: #000080; color: #ffffff; }}
QCheckBox, QRadioButton {{ color: #000000; }}
QMessageBox {{ background: #c0c0c0; }}
"""


def qss_for(theme: str, mode: str, accent) -> str:
    if theme == "win98":
        return win98_qss()
    return material_qss(accent, mode == "dark")


def apply(app, theme: str, mode: str, accent) -> None:
    app.setStyleSheet(qss_for(theme, mode, accent))