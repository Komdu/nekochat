"""Качает Roboto (woff2) с Google Fonts и создаёт @font-face для локального хостинга.

    python scripts/fetch_roboto.py

Сохраняет файлы в app/static/fonts/ и пишет app/static/fonts/fonts.css,
который подключается из index.html. Сабсеты: latin + cyrillic (400/500/700).
"""
import re
import urllib.request
from pathlib import Path

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
CSS_URL = "https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap"
ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "app" / "static" / "fonts"
WANT = {"latin", "cyrillic"}


def get(url, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read() if binary else r.read().decode("utf-8")


def main():
    FONTS.mkdir(parents=True, exist_ok=True)
    css = get(CSS_URL)
    blocks = re.findall(r"/\*\s*([\w-]+)\s*\*/\s*(@font-face\s*\{[^}]+\})", css)
    out, n = [], 0
    for subset, block in blocks:
        if subset not in WANT:
            continue
        url_m = re.search(r"url\((https://[^)]+\.woff2)\)", block)
        w_m = re.search(r"font-weight:\s*(\d+)", block)
        if not url_m or not w_m:
            continue
        name = f"roboto-{w_m.group(1)}-{subset}.woff2"
        data = get(url_m.group(1), binary=True)
        (FONTS / name).write_bytes(data)
        n += 1
        face = block.replace(url_m.group(1), "/fonts/" + name)
        out.append(face)
    (FONTS / "fonts.css").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"FONTS-OK {n} files -> {FONTS}")


if __name__ == "__main__":
    main()
