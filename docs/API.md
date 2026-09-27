# Nekochat API — контракт для кастомных клиентов

Сервер — REST (+WebSocket) бэкенд. Веб-UI (`/web/`) — лишь один из клиентов.
Свой клиент можно писать на чём угодно: всё общение идёт по этому контракту.

- Базовый URL: `http://<host>:<port>` (или `https://…`).
- Формат: JSON (`application/json`), ошибки — `{"detail": "..."}` со статусами HTTP.
- Документация: `/docs` (общая, рендер из `docs/` репозитория), Swagger UI по REST: `/api/docs`, машинный спек: `/api/openapi.json` (алиас — `/openapi.json`).
- CORS: `allow-origin: *` (для браузерных кастомных UIs).

## Аутентификация

JWT (HS256), `sub` = id пользователя, живёт 7 дней.

| Метод | Путь | Тело | Ответ |
|---|---|---|---|
| POST | `/auth/register` | `{username, password, display_name}` | `Token` |
| POST | `/auth/login` | `{username, password}` | `Token` |

`Token = {access_token: string, token_type: "bearer", user: UserOut}`

Все защищённые руты требуют заголовка `Authorization: Bearer <access_token>`.

### Пользователь (`UserOut`)

```json
{
  "id": 1, "username": "komdu", "display_name": "Komdu",
  "avatar": "1_ab12.png", "bio": null, "profile_color": "#ff8800",
  "status": null, "banner": null, "is_online": true
}
```

Аватары/баннеры отдаются по `/avatars/<filename>` (публично).

## REST-роуты

### Профиль
| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/me` | свой профиль (`UserOut`) |
| PUT | `/users/me/profile` | `{bio?, status?, profile_color?}` → `UserOut` (цвет `#RRGGBB` либо `null`) |
| POST | `/users/me/avatar` | multipart `file` (PNG/JPEG/WebP/GIF, ≤5 МБ) → `UserOut` |
| POST | `/users/me/banner` | multipart `file` (там же лимиты) → `UserOut` |

### Люди
| Метод | Путь | Описание |
|---|---|---|
| GET | `/users` | все пользователи, кроме себя (`list[UserOut]`) |
| GET | `/users/conversations/me` | список личных переписок: `[{conversation_id, user: UserOut}]` |
| GET | `/users/{other_id}/messages` | история ЛС (диалог создаётся по надобности), `list[DirectMessageOut]` |

`DirectMessageOut = {id, content, created_at, sender: UserOut}`

### Комнаты
| Метод | Путь | Описание |
|---|---|---|
| GET | `/rooms` | все комнаты (`list[RoomOut]`) |
| POST | `/rooms` | создать `{name}` → `RoomOut` (создатель становится участником) |
| GET | `/rooms/{room_id}/messages` | история комнаты `list[MessageOut]`, только для участников |
| POST | `/rooms/{room_id}/join` | вступить → `RoomOut` |
| POST | `/rooms/{room_id}/members` | добавить участника `{username}` → `RoomOut` |

`RoomOut = {id, name, created_at, member_count, members: [UserOut]}`
`MessageOut = {id, content, created_at, user: UserOut}`

### Публичное
| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/server-info` | метаданные сервера (см. ниже) |
| GET | `/api/health` | `{ok: true, version}` — пульс без авторизации |
| GET | `/download` | собранный клиент (exe), если файл загружен на сервер |
| GET | `/avatars/{filename}` | файл аватарки/баннера (public, cache 1 год) |

`/api/server-info`:

```json
{
  "name": "Nekochat", "description": "",
  "version": "0.9.0", "sqlite": true,
  "download_url": null, "download_size": "190 МБ"
}
```

`download_url` и `download_size` — для лендинга; если `download_url` задан
в `config.yml` (например GitHub Release), клиенты качают оттуда, иначе `/download`.

## WebSocket

`ws://<host>/ws?token=<access_token>` (или `wss://`).

- Ошибка авторизации → закрытие с кодом `4401`.
- При подключении все, включая вас, получают `{"type":"status","user_id":N,"online":true}`.
- При отключении — `online: false`.

### Клиент → сервер

| type | поля | смысл |
|---|---|---|
| `room_message` | `room_id`, `content` | сообщение в комнату |
| `direct_message` | `to_id`, `content` | личное сообщение |
| `call` / `call_answer` / `call_hangup` | `to_id` **или** `room_id` | сигналинг звонка (реле) |
| `call_audio` | `to_id` **или** `room_id`, `call_id`, `seq`, `audio` | Opus-кадр (base64, 20мс) — сервер пересылает адресату |
| `screen_start` / `screen_stop` | `to_id` **или** `room_id`, `call_id` | включить/выключить демонстрацию экрана (реле) |
| `screen_frame` | `to_id` **или** `room_id`, `call_id`, `seq`, `key`, `data` | видео-кадр (VP8/VP9/AV1, base64) — сервер пересылает адресату |
| `ping` | — | → `pong` |

### Сервер → клиент

| type | поля |
|---|---|
| `status` | `user_id`, `online` |
| `room_message` | `room_id`, `message: {id, content, created_at, user_id}` |
| `direct_message` | `conversation_id`, `from_id`, `message: {id, content, created_at, sender_id}` |
| `call*` (релей) | исходные поля + `from_id` |
| `error` | `message` |

WebRTC не используется: аудио звонка идёт Opus'ом по тому же WebSocket
(`call_audio`), демонстрация экрана — видео-кадрами (`screen_frame`),
сервер — реле (без эха, без SDP/ICE).

## Голосовой канал комнаты (ГС)

Голосовой канал — общий «голосовой чат» комнаты: участник комнаты заходит
в канал и говорит, все остальные в канале слышат его (микширование N−1
на клиенте, без WebRTC — Opus по тому же `/ws` через релей сервера).
Отдельного REST нет — канал целиком живёт в WS-сообщениях.

### Как использовать (порядок для клиента)

1. Подключиться к `/ws` (JWT в query).
2. **Войти в канал** — анонс присутствия:
   ```json
   {"type": "call", "room_id": 5, "call_id": "c1kq…"}
   ```
   Без `to_id`. Сервер релеит анонс всем участникам комнаты (эхо — и отправителю).
   Звонка-ринга нет: те, кто уже в комнате, видят ненавязчивый инвайт
   «войти в канал».
3. **Принять приглашение** (если ещё не в канале):
   ```json
   {"type": "call_answer", "room_id": 5, "call_id": "c1kq…"}
   ```
4. **Говорить** — Opus-кадр 20 мс (base64); сервер шлёт **всем, кроме отправителя**:
   ```json
   {"type": "call_audio", "room_id": 5, "call_id": "c1kq…", "seq": 42, "audio": "<base64>"}
   ```
   Клиент держит по декодеру на каждого собеседника (N−1) и сводит поток в микшер.
   Опоздавший участник «догоняется» по первому `call_audio` от него (поле `from_id`).
5. **Выйти из канала**:
   ```json
   {"type": "call_hangup", "room_id": 5, "call_id": "c1kq…", "reason": "leave"}
   ```

### Присутствие в канале

Сервер — только реле, REST-списка «кто в канале» нет. Участники выводятся из
релейных сообщений: `from_id` в `call` / `call_answer` / `call_audio` добавляет
участника, `call_hangup` — убирает. Если клиент упал без `call_hangup`, остальные
видят его выход по исчезновению его кадров / по своему `call_hangup`.

### Демонстрация экрана в канале

Те же сообщения, что в 1-1, но с `room_id` вместо `to_id`:
`screen_start` → `screen_frame` (реле всем, кроме отправителя) → `screen_stop`.
Шарер в канале один: `screen_start` от нового участника переключает экран на него,
`screen_stop` от текущего шарера гасит экран.

## Админ-панель (`/admin`)

Отдельная от обычных пользователей панель управления сервером — **не REST** для клиентов.

- **Вход:** при старте сервер генерирует случайный хэш и печатает его в консоль
  (`docker logs nekochat-app-1 | grep HASH`). Панель — `POST /admin/login` c `{"hash": "..."}`,
  дальше сессия держится в HttpOnly-куке. Хэш сбрасывается при каждом перезапуске сервера,
  вместе с ним сбрасываются и все админ-сессии.
- **Возможности** (все роуты под `/admin/*`, требуют сессию):
  - `GET /admin/stats` — счётчики (пользователи, онлайн, баны, комнаты, сообщения, WS).
  - `GET /admin/users?q=`, `GET /admin/users/{id}` — список/карточка пользователя.
  - `POST /admin/users/{id}/ban|unban` — блокировка (логин и WS закрываются с 4403).
  - `POST /admin/users/{id}/edit` — display_name / status / bio / profile_color.
  - `POST /admin/users/{id}/reset-password` — временный пароль в ответе.
  - `DELETE /admin/users/{id}` — удаление с каскадом (сообщения, личные переписки, пустые комнаты).
  - `GET /admin/messages`, `GET /admin/direct-messages`, `DELETE /messages/{id}`, `/direct-messages/{id}`.
  - `GET /admin/rooms`, `DELETE /admin/rooms/{id}`.
- UI — `/admin` (одностраничный HTML, vanilla JS).

## Заметки для клиентов

- Валидация: короткие поля — до 100 символов (status), сообщения пустые игнорируются.
- Ограничение прав: сообщение/звонок в комнату — только участника.
- Веб-UI как эталонный клиент: `/web/` (тот же код, что и в десктоп-приложении).