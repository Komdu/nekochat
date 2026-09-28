"""Генерация иконок PWA из монохромной иконки приложения.

Исходник — icon-app-1024.png (белый кот на чёрной плашке) либо
desktop/src-tauri/icons/icon.png, если исходника нет.

Что делает:
  - обычные иконки 192 и 512 (purpose: any) — для вкладок и установки;
  - maskable-иконка 512 — та же картинка, но вписанная в «безопасную зону»
    80%: Android обрезает maskable-иконки по кругу или скруглённому квадрату,
    и логотип без отступов срезается по ушам.

Запуск:
  .\\.venv-build\\Scripts\\python.exe scripts\\make_pwa_icons.py
"""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC_CANDIDATES = [
    ROOT / "icon-app-1024.png",
    ROOT / "desktop" / "src-tauri" / "icons" / "icon.png",
]
OUT_DIR = ROOT / "web" / "public"

# доля отступа для maskable: 10% с каждой стороны -> логотип занимает 80%
MASKABLE_SCALE = 0.80


def load_source() -> Image.Image:
    for p in SRC_CANDIDATES:
        if p.exists():
            print(f"исходник: {p}")
            return Image.open(p).convert("RGBA")
    raise SystemExit("не найден ни один исходник иконки:\n  " +
                     "\n  ".join(str(p) for p in SRC_CANDIDATES))


def save_any(im: Image.Image, size: int, name: str) -> None:
    out = im.resize((size, size), Image.LANCZOS)
    path = OUT_DIR / name
    out.save(path, "PNG", optimize=True)
    print(f"  {name}  {size}x{size}  {path.stat().st_size // 1024} КБ")


def save_maskable(im: Image.Image, size: int, name: str) -> None:
    """Кладём логотип в центр чёрного квадрата с отступом.

    Фон обязателен: иначе маска Android покажет белое поле вместо иконки,
    потому что альфа-канал в maskable-схеме не участвует.
    """
    inner = int(size * MASKABLE_SCALE)
    logo = im.resize((inner, inner), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 255))
    off = (size - inner) // 2
    canvas.paste(logo, (off, off), logo)
    path = OUT_DIR / name
    canvas.save(path, "PNG", optimize=True)
    print(f"  {name}  {size}x{size}  maskable, логотип {inner}px  "
          f"{path.stat().st_size // 1024} КБ")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    src = load_source()
    print(f"исходник {src.size[0]}x{src.size[1]}")

    print("обычные иконки:")
    for size in (192, 512):
        save_any(src, size, f"icon-{size}.png")
    # favicon: мелкие размеры браузер возьмёт сам
    save_any(src, 32, "favicon-32.png")

    print("maskable (с отступом под маску Android):")
    save_maskable(src, 512, "maskable-512.png")

    print(f"\nготово -> {OUT_DIR}")


if __name__ == "__main__":
    main()
