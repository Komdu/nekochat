"""GET /docs — общая документация проекта вместо авто-Swagger UI.

Читает docs/*.md рядом с сервером и рендерит одну HTML-страницу лёгким
рендерером подмножества Markdown (заголовки, код-блоки, таблицы, списки,
ссылки, жирный/код-инлайны). Никаких внешних зависимостей.
"""

import re
import sys
from pathlib import Path

FILES = [
    ("README.md", "Введение"),
    ("API.md", "API — REST + WebSocket"),
    ("THEMES.md", "Темы клиентов"),
    ("WIN_SERVER.md", "Локальный сервер (Windows)"),
    ("ROADMAP.md", "Что дальше"),
]


def _docs_dir() -> Path:
    if getattr(sys, "frozen", False):
        # в упакованном сервере docs/ кладём в _MEIPASS/docs (см. server_win.spec)
        return Path(getattr(sys, "_MEIPASS", Path())) / "docs"
    return Path(__file__).resolve().parent.parent / "docs"


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_INLINE_RE = re.compile(
    r"(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))"
)


def _inline(s: str) -> str:
    def repl(m):
        tok = m.group(1)
        if tok.startswith("`"):
            return f'<code>{_esc(tok[1:-1])}</code>'
        if tok.startswith("**"):
            return f"<strong>{_inline(tok[2:-2])}</strong>"
        m_link = re.match(r"\[([^\]]+)\]\(([^)]+)\)", tok)
        if m_link:
            href = m_link.group(2)
            return f'<a href="{_esc(href)}">{_esc(m_link.group(1))}</a>'
        return _esc(tok)
    return _INLINE_RE.sub(repl, _esc(s))


def _render_table(rows: list[list[str]]) -> str:
    body = "".join(
        "<tr>" + "".join(f"<td>{_inline(c.strip())}</td>" for c in row) + "</tr>"
        for row in rows
    )
    return f'<div class="table-wrap"><table>{body}</table></div>'


def _render_lines(lines: list[str]) -> str:
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].rstrip("\n")

        # код-блок
        if line.startswith("```"):
            acc: list[str] = []
            i += 1
            while i < n and not lines[i].startswith("```"):
                acc.append(lines[i].rstrip("\n"))
                i += 1
            i += 1  # закрывающий ```
            out.append("<pre><code>" + _esc("\n".join(acc)) + "</code></pre>")
            continue

        # заголовки
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{_inline(m.group(2))}</h{lvl}>")
            i += 1
            continue

        # таблица: строка с | и следующая строка-разделитель |---|
        if re.match(r"^\s*\|", line) and i + 1 < n and re.match(r"^\s*\|[\s:|-]+\|?\s*$", lines[i + 1]):
            if re.search(r"---", lines[i + 1]):
                header = [c for c in line.strip().strip("|").split("|")]
                rows: list[list[str]] = []
                j = i + 2
                while j < n and lines[j].strip().startswith("|"):
                    rows.append([c for c in lines[j].strip().lstrip("|").rstrip("|").split("|")])
                    j += 1
                out.append(
                    '<div class="table-wrap"><table><thead><tr>'
                    + "".join(f"<th>{_inline(c.strip())}</th>" for c in header)
                    + "</tr></thead><tbody>"
                    + "".join(
                        "<tr>" + "".join(f"<td>{_inline(c.strip())}</td>" for c in row) + "</tr>"
                        for row in rows
                    )
                    + "</tbody></table></div>"
                )
                i = j
                continue

        # списки
        m_list = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", line)
        if m_list:
            items: list[str] = [m_list.group(3)]
            j = i + 1
            while j < n:
                m2 = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", lines[j])
                if m2:
                    items.append(m2.group(3))
                    j += 1
                else:
                    break
            lis = "".join(f"<li>{_inline(it)}</li>" for it in items)
            out.append(f"<ul>{lis}</ul>")
            i = j
            continue

        # цитата
        if line.startswith(">"):
            quote: list[str] = []
            j = i
            while j < n and lines[j].startswith(">"):
                quote.append(lines[j][1:].lstrip())
                j += 1
            out.append("<blockquote>" + _inline(" ".join(quote)) + "</blockquote>")
            i = j
            continue

        # hr
        if re.match(r"^---+$", line.strip()):
            out.append("<hr>")
            i += 1
            continue

        # пустая строка — просто пропуск
        if not line.strip():
            i += 1
            continue

        # абзац (склеиваем до следующей пустой/особой строки)
        para: list[str] = [line]
        j = i + 1
        while j < n:
            nxt = lines[j].rstrip("\n")
            if not nxt.strip() or nxt.startswith(("#", "```", "-", "*", ">", "1.", "2.")) or re.match(r"^\s*\|", nxt):
                break
            para.append(nxt)
            j += 1
        out.append(f"<p>{_inline(' '.join(para))}</p>")
        i = j

    return "\n".join(out)


def _read_file(dir_: Path, name: str) -> str:
    try:
        return (dir_ / name).read_text(encoding="utf-8")
    except (OSError, IOError):
        return ""


def docs_page_html() -> str:
    dir_ = _docs_dir()
    sections: list[str] = []
    toc = ""
    for name, title in FILES:
        text = _read_file(dir_, name)
        anchor = name.replace(".", "-")
        if not text:
            text = "_Документ не доступен на этом сервере._"
        sections.append(
            f'<section id="{anchor}"><h1>{_esc(title)}</h1>{_render_lines(text.splitlines())}</section>'
        )
        toc += f'<a href="#{anchor}">{_esc(title)}</a>'
    if not any(_read_file(dir_, n) for n, _ in FILES):
        sections.append(
            "<p>На этом сервере папка <code>docs/</code> не доступна. "
            "Полная документация — в репозитории проекта: <code>docs/</code>.</p>"
        )
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nekochat — документация</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: #0f0d13; color: #e6e0e9;
         font: 15px/1.55 'Segoe UI', Roboto, sans-serif; }}
  .wrap {{ max-width: 960px; margin: 0 auto; padding: 28px 22px 60px; }}
  header {{ display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap;
           padding-bottom: 14px; border-bottom: 1px solid #49454f; }}
  header h1 {{ font-size: 22px; margin: 0; color: #d0bcff; }}
  nav {{ display: flex; gap: 8px; flex-wrap: wrap; margin: 12px 0 4px; }}
  nav a {{ color: #d0bcff; text-decoration: none; background: #1d1b22;
          padding: 4px 12px; border-radius: 999px; font-size: 13px; }}
  nav a:hover {{ background: #2b2930; }}
  section {{ margin-top: 26px; }}
  h1 {{ font-size: 20px; color: #d0bcff; }}
  h2 {{ font-size: 17px; color: #eaddff; margin-top: 26px; }}
  h3 {{ font-size: 15px; color: #eaddff; }}
  a {{ color: #d0bcff; }}
  code {{ background: #211f26; border: 1px solid #49454f; border-radius: 6px;
         padding: 1px 5px; font: 13px Consolas, monospace; }}
  pre {{ background: #141218; border: 1px solid #49454f; border-radius: 10px;
        padding: 12px 14px; overflow-x: auto; }}
  pre code {{ background: transparent; border: none; padding: 0; }}
  table {{ border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 14px; }}
  th, td {{ border: 1px solid #49454f; padding: 6px 10px; text-align: left; }}
  th {{ background: #1d1b22; color: #eaddff; }}
  tr:nth-child(even) td {{ background: #141218; }}
  ul {{ padding-left: 22px; }}
  li {{ margin: 3px 0; }}
  blockquote {{ margin: 10px 0; padding: 6px 14px; border-left: 3px solid #4f378b;
                background: #141218; color: #cac4d0; }}
  hr {{ border: none; border-top: 1px solid #49454f; margin: 20px 0; }}
  .table-wrap {{ overflow-x: auto; }}
  @media (max-width: 640px) {{ body {{ font-size: 14px; }} }}
</style>
</head>
<body>
<div class="wrap">
  <header><h1>Nekochat — документация</h1></header>
  <nav>{toc}</nav>
  {''.join(sections)}
</div>
</body>
</html>
"""