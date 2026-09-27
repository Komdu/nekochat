# Темы клиентов

У клиентов (десктоп-приложение и веб-чат) три темы:

1. **Material You** — акцентная M3-палитра (динамическая, считается из цвета).
2. **Win98** — классический Windows 98 (teal-рабочий стол, серые панели, bevel-кнопки).
3. **Из файла** — кастомная тема `%APPDATA%\nekochat\theme.json` (переопределяет любые
   токены поверх любой базы).

Эталонная реализация: `desktop/src/theme.ts` + `desktop/src/you.ts` — точные порты
`client_ui/theme.py` + `client_ui/you.py` (палитра сверяется побайтово, см. `tmp/pal_test/`).

## Где хранятся настройки

Десктоп-клиент (React/Tauri): localStorage WebView2-профиля (`nk.*`).

| Ключ | Значение |
|---|---|
| `nk.theme` | `material` \| `win98` \| `file` |
| `nk.mode` | `dark` \| `light` |
| `nk.accent` | имя пресета или hex `#rrggbb` |
| `nk.token` / `nk.user` / `nk.base` | сессия и сервер |

## Material You

- Базовая палитра генерируется из акцента по алгоритму M3 (OKLCH комнатного
  пространства, порт `you.py`).
- Пресеты акцентов (`desktop/src/you.ts`):

  | имя | hex |
  |---|---|
  | purple | `#6750a4` |
  | indigo | `#283593` |
  | blue | `#1565c0` |
  | teal | `#00695c` |
  | green | `#1b5e20` |
  | pink | `#ad1457` |
  | red | `#b71c1c` |
  | orange | `#bf360c` |

- Дополнительно в «Настройках» есть «радужный» свотч с color-picker: любой hex
  работает как акцент (`nk.accent = #rrggbb`).
- Режимы: тёмная / светлая. Для тёмных акцентов поверхности «поднимаются»
  подмешиванием нейтральной базы (`_lift_dark` в theme.py / `liftDark` в theme.ts),
  чтобы UI не становился почти-чёрным.

## Win98

- Стили-переопределения на `html[data-theme="win98"]`: teal-рабочий стол,
  серые панели, bevel-кнопки с «нажатием», белые списки с inset-рамкой,
  жёлтые пузыри `#ffffc1` с чёрным текстом, скроллбары 16px.
- Эквивалент QSS: `win98_qss()` в `client_ui/theme.py`.

## Кастомная тема из файла

Путь: `%APPDATA%\nekochat\theme.json` (Windows). Если файл есть — в
`Настройки → Тема` появляется опция «Из файла» и кнопка «Перечитать файл»
(перезапуск не нужен). Пример: `desktop/theme.example.json`.

```json
{
  "name": "Мой пример",
  "mode": "dark",
  "accent": "#00b8a9",
  "colors": {
    "desk": "#0b0f14",
    "panel": "#151c24",
    "mine": "#0e7490"
  }
}
```

Поля:

- `name` (строка) — название, показывается в настройках. Опционально.
- `mode` (`"dark"` | `"light"`) — база. Опционально (по умолчанию из настроек).
- `accent` (hex `#rrggbb`) — акцент, из которого считается вся M3-палитра. Опционально.
- `colors` — переопределение токенов поверх готовой палитры. Опционально.
  Ключи — имена токенов (см. ниже), значения — `#rrggbb`. Некорректные
  значения отбрасываются; можно также задавать готовые CSS-переменные
  ключами вида `--имя-переменной`.

### Доступные токены

Страничные: `desk panel panel_hover divider text1 muted title1 title2 link mine
mine_sender chat_sub focus`.

Material: `primary on_primary primary_container on_primary_container secondary
on_secondary secondary_container on_secondary_container surface on_surface
on_surface_variant outline outline_variant surface_lowest surface_low
surface_high surface_highest`.

Полный список соответствий «токен → CSS-переменная» — `TOKEN_TO_VAR` в
`desktop/src/theme.ts`.

### Технически

- Чтение файла: Tauri-команда `read_theme_file` (`desktop/src-tauri/src/lib.rs`),
  путь `%APPDATA%\nekochat\theme.json`.
- Применение: `applyTheme("file", ...)` вычисляет M3-базу из `accent`/`mode`,
  затем `colors`-оверрайды вешаются как CSS-переменные на `<html>`.
- Сброс: удалить файл, «Перечитать файл», выбрать другую тему.