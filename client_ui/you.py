"""Material You — динамическая M3-палитра из цвета-акцента (OKLCH).

Точный порт генератора `window.You` из app/static/web/index.html:
тот же набор токенов и та же математика (sRGB-gamut clamping, затемнение
светлого primary до контраста белого текста).
"""
import math
import re

PRESETS = {
    "purple": "#6750a4",
    "indigo": "#283593",
    "blue": "#1565c0",
    "teal": "#00695c",
    "green": "#1b5e20",
    "pink": "#ad1457",
    "red": "#b71c1c",
    "orange": "#bf360c",
}

_HEX = re.compile(r"^#?([0-9a-f]{6})$", re.I)


def _unrgb(v: float) -> float:
    v /= 255.0
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def src_lch(hex_: str):
    """Hex-цвет -> (L, C, h) в OKLCH (h в градусах)."""
    m = _HEX.match(hex_ if isinstance(hex_, str) else "")
    if not m:
        return (0.45, 0.17, 275.0)
    n = int(m.group(1), 16)
    r, g, b = _unrgb((n >> 16) & 255), _unrgb((n >> 8) & 255), _unrgb(n & 255)
    l_ = math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    mm = math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s = math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    L = 0.2104542553 * l_ + 0.7936177850 * mm - 0.0040720468 * s
    a = 1.9779984951 * l_ - 2.4285922050 * mm + 0.4505937099 * s
    bb = 0.0259040371 * l_ + 0.7827717662 * mm - 0.8086757660 * s
    return (L, math.hypot(a, bb), math.degrees(math.atan2(bb, a)))


def tone(L: float, C: float, h: float) -> str:
    """OKLCH -> hex с прижатием к sRGB-гейму (совпадает с JS-версией)."""
    for _ in range(30):
        a = C * math.cos(math.radians(h))
        b = C * math.sin(math.radians(h))
        l_ = L + 0.3963377774 * a + 0.2158037573 * b
        m_ = L - 0.1055613458 * a - 0.0638541728 * b
        s_ = L - 0.0894841775 * a - 1.2914855480 * b
        l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
        R = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
        G = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
        B = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
        if -0.0005 <= R <= 1.0005 and -0.0005 <= G <= 1.0005 and -0.0005 <= B <= 1.0005:
            parts = []
            for x in (R, G, B):
                x = max(0.0, min(1.0, x))
                y = 12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055
                parts.append(format(max(0, min(255, round(y * 255))), "02x"))
            return "#" + "".join(parts)
        C *= 0.93
        if C < 0.002:
            break
    return "#888888"


def lum(hex_: str) -> float:
    """Относительная светимость (для проверки контраста)."""
    m = _HEX.match(hex_ or "")
    if not m:
        return 1.0
    n = int(m.group(1), 16)

    def f(c: int) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * f((n >> 16) & 255) + 0.7152 * f((n >> 8) & 255) + 0.0722 * f(n & 255)


# длинные имена токенов — как в веб-версии (--md-sys-color-*)
TRACK = [
    "--md-sys-color-primary", "--md-sys-color-on-primary",
    "--md-sys-color-primary-container", "--md-sys-color-on-primary-container",
    "--md-sys-color-secondary", "--md-sys-color-on-secondary",
    "--md-sys-color-secondary-container", "--md-sys-color-on-secondary-container",
    "--md-sys-color-surface", "--md-sys-color-on-surface",
    "--md-sys-color-on-surface-variant", "--md-sys-color-outline",
    "--md-sys-color-outline-variant",
    "--md-sys-color-surface-container-lowest",
    "--md-sys-color-surface-container-low",
    "--md-sys-color-surface-container",
    "--md-sys-color-surface-container-high",
    "--md-sys-color-surface-container-highest",
    "--title1", "--title2", "--focus", "--link", "--mine", "--mine-sender",
    "--chat-sub", "--desk", "--panel", "--panel-hover", "--divider",
    "--text1", "--muted", "--win-text",
]


def tokens(hex_: str, dark: bool) -> dict:
    """Полный набор токенов из акцента для режима light/dark (ключи без '--')."""
    L, C, h = src_lch(hex_)
    C = max(0.10, min(0.20, C))

    def sc(f: float) -> float:
        return C * f

    t = {}
    t["md-sys-color-primary"] = tone(0.80 if dark else 0.45, sc(1), h)
    t["md-sys-color-on-primary"] = tone(0.22, sc(0.6), h) if dark else "#ffffff"
    t["md-sys-color-primary-container"] = tone(0.30 if dark else 0.90, sc(0.7), h)
    t["md-sys-color-on-primary-container"] = tone(0.88 if dark else 0.15, sc(0.8), h)
    t["md-sys-color-secondary"] = tone(0.80 if dark else 0.45, sc(0.7), h)
    t["md-sys-color-on-secondary"] = tone(0.22, sc(0.5), h) if dark else "#ffffff"
    t["md-sys-color-secondary-container"] = tone(0.30 if dark else 0.90, sc(0.5), h)
    t["md-sys-color-on-secondary-container"] = tone(0.88 if dark else 0.15, sc(0.7), h)
    t["md-sys-color-surface"] = tone(0.17 if dark else 0.98, sc(0.10), h)
    t["md-sys-color-on-surface"] = tone(0.94 if dark else 0.13, sc(0.14), h)
    t["md-sys-color-on-surface-variant"] = tone(0.80 if dark else 0.31, sc(0.16), h)
    t["md-sys-color-outline"] = tone(0.62 if dark else 0.45, sc(0.16), h)
    t["md-sys-color-outline-variant"] = tone(0.30 if dark else 0.85, sc(0.14), h)
    t["md-sys-color-surface-container-lowest"] = tone(0.06 if dark else 1.00, sc(0.08), h)
    t["md-sys-color-surface-container-low"] = tone(0.14 if dark else 0.97, sc(0.10), h)
    t["md-sys-color-surface-container"] = tone(0.17 if dark else 0.98, sc(0.11), h)
    t["md-sys-color-surface-container-high"] = tone(0.21 if dark else 0.95, sc(0.13), h)
    t["md-sys-color-surface-container-highest"] = tone(0.26 if dark else 0.92, sc(0.16), h)
    # страница (страницные css-переменные веб-версии)
    t["title1"] = tone(0.42 if dark else 0.45, sc(1), h)
    t["title2"] = tone(0.58 if dark else 0.62, sc(0.9), h)
    t["focus"] = tone(0.30, sc(0.45), h) if dark else tone(0.93, sc(0.5), h)
    t["link"] = tone(0.80 if dark else 0.45, sc(1), h)
    t["mine"] = tone(0.30 if dark else 0.90, sc(0.7), h)
    t["mine-sender"] = tone(0.88 if dark else 0.15, sc(0.8), h)
    t["chat-sub"] = tone(0.90 if dark else 0.86, sc(0.4), h)
    t["desk"] = tone(0.11 if dark else 0.95, sc(0.10), h)
    t["panel"] = tone(0.17 if dark else 0.98, sc(0.12), h)
    t["panel-hover"] = tone(0.24 if dark else 0.94, sc(0.15), h)
    t["divider"] = tone(0.32 if dark else 0.89, sc(0.15), h)
    t["text1"] = tone(0.94 if dark else 0.13, sc(0.14), h)
    t["muted"] = tone(0.74 if dark else 0.42, sc(0.14), h)
    t["win-text"] = t["text1"]
    if not dark:  # светлый primary должен держать белый текст (>= ~4.4:1)
        for _ in range(6):
            if lum(t["md-sys-color-primary"]) <= 0.17:
                break
            nL, _, _ = src_lch(t["md-sys-color-primary"])
            t["md-sys-color-primary"] = tone(max(0.30, nL - 0.04), sc(1), h)
    return t


def hex_for(v: str) -> str:
    """Имя пресета ('blue') или '#rrggbb' -> hex акцента (дефолт purple)."""
    if isinstance(v, str) and _HEX.match(v):
        return v
    return PRESETS.get(v, PRESETS["purple"])