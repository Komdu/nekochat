# desktop/ — нативный клиент на React + Tauri

Новый нативный клиент Nekochat: **React + TypeScript + Vite** (интерфейс) поверх
**Tauri v2** (окно/WebView2). Заменяет PySide6-версию (`client_ui/`) — старый
клиент остаётся в `client_app.py` до достижения полного паритета.

Один и тот же фронтенд собирается и в десктоп, и легко отдаётся как веб-страница
(на сервере CORS уже `*`, поэтому реакт-клиент работает и в браузере против прода).

## Стек

- `npm run dev` — Vite dev-сервер на `http://localhost:1420`, API ходит напрямую (CORS `*`)
- `npm run build` — `tsc --noEmit` + `vite build` → `dist/`
- `npm run tauri -- build --debug` / `--release` — сборка exe
- Релиз с установщиком: `npm run tauri -- build --release --bundles nsis`
  (или `scripts\build_tauri.bat`)

## Структура

```
src/
  main.tsx, App.tsx        — корень, фазы boot/login/ready
  store.tsx                — состояние: сессии, списки, WS, оптимистичная отправка
  api.ts                   — REST + WebSocket (порт client_ui/api.py)
  you.ts                   — M3-палитра OKLCH (точный порт client_ui/you.py)
  theme.ts                 — токены тем Material/Win98 (порт theme.py, включая _lift_dark)
  format.ts                — crc32, цвета аватаров, время (порт chat.py)
  ui/                      — LoginPage, ChatPage, Sidebar, диалоги, Avatar/Tile
  styles.css               — стили в духе лендинга (CSS-переменные)
src-tauri/                 — оболочка Tauri (minimal, без плагинов)
```

## Контракт портов

- Палитра и токены тем сверены с Python побайтово
  (`tmp/pal_test/*` — компаратор you.ts ↔ you.py, theme.ts ↔ theme.py).
- Поведение: зомби-сессия (401 → логаут), оптимистичные сообщения, дедуп по id,
  `seen`-сеты, сортировка списков, аватарки/онлайн-точки, пузыри (свои справа).

## Настройки/сессия

Хранятся в localStorage WebView2-профиля (`nk.*`): тема/режим/акцент, токен,
сервер, последний открытый чат. В десктопе переживают перезапуск.

Акцент — любой пресет или свой цвет («радужный» свотч с color-picker):
M3-палитра пересчитывается на лету из выбранного hex.

## Кастомная тема из файла

Путь: `%APPDATA%\nekochat\theme.json` (Windows). Если файл есть, в
Настройках → Тема появляется опция «Из файла» (плюс кнопка «Перечитать
файл» после правки файла). Пример: `theme.example.json`.

Структура:

```json
{
  "name": "Мой пример",        // название в настройках (опционально)
  "mode": "dark",              // "dark" | "light" (опционально)
  "accent": "#00b8a9",         // любой hex — база для M3-палитры (опционально)
  "colors": {                  // переопределение токенов поверх палитры (опционально)
    "desk": "#0b0f14",
    "panel": "#151c24",
    "mine": "#0e7490"
  }
}
```

Ключи в `colors` — любые из токенов темы (`desk`, `panel`, `panel_hover`,
`text1`, `muted`, `title1`, `link`, `mine`, `mine_sender`, `primary`,
`on_primary`, `primary_container`, `surface_lowest`, `surface_high` и т.д.,
недопустимые значения отбрасываются). Можно также указывать готовые
CSS-переменные ключами вида `--custom-var`.

## Требования для сборки

- Node.js LTS + npm
- Rust (rustup) — MSVC-тулчейн
- Visual Studio Build Tools (C++ workload) — для компиляции крэйтов
- WebView2 Runtime (обычно уже есть в Windows 11)