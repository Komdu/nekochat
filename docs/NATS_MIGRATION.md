# NATS-транспорт Nekochat (Phase 1)

## Зачем

Диагностика (CLI-зонд + server-логи) показала корень нестабильных звонков:

- idle-WS-соединения через Cloudflare-туннель режутся раз в **~125 c** (код 1006);
- клиент об этом **не узнаёт** — сокет с его стороны остаётся «живым» (half-open);
- сервер держит мёртвый сокет в `active` и `is_online=true`, `_send_guarded` молча
  льёт call/call_audio в пустоту → «вечный connecting» и «нет call_answer»;
- наш десктоп переживает это (heartbeat 10с + автореконнект 1с→15с), андроид-клиент
  друга — нет (нет реконнекта вообще).

Решение (принято): **перевести транспорт на NATS через тот же туннель как WSS.**
Резы туннеля останутся, но NATS-клиенты штатно переподключаются, а liveness
проверяется на протокольном уровне (ping/pong NATS) — half-open исчезает.

## Архитектура Phase 1: «NATS = транспорт, приложение остаётся хабом»

```
Браузер/WebView (nats.ws)  ──WSS──┐
Android (nats.java)        ──WSS──┤    Cloudflare-туннель        nginx :8000 (пути: /nats→8081, прочее→8001)
                                  ├──► /nats ──────────────► nats-server :8081 (WS) ──:4222──► app (мост)
                                  │                       (ping 10с,          │
Десктоп флаг nc_transport=nats ───┘                        half-open guard)   ▼
                                                                   handle_ws_message
                                                           (та же логика, что /ws и /push)
```

- **Субъекты**: `nkc.in.<uid>` (клиент→сервер), `nkc.out.<uid>` (сервер→клиент).
  Клиент подписан на свой `out`, публикует в свой `in` — сервер релеит (как сейчас /ws).
- **Presence**: юзер «online» с первого входящего сообщения; после
  `NATS_SILENCE_S` (45 с) тишины мост считает его offline, выкидывает очередь и
  рассылает `status online=false` — это и есть half-open guard на уровне приложения.
- **Liveness канала**: `nats-server` шлёт клиентам протокольные PING каждые 10 с
  (`ping_interval`), 2 пропуска → сервер сам сбрасывает мёртвый клиент. NATS-клиенты
  (nats.ws / nats.java / nats-py) переподключаются сами.
- **Auth**: один статичный юзер/пароль nats-server (`NATS_WS_USER`/`NATS_WS_PASS`),
  выдаются клиенту через REST `GET /nats/creds` (по JWT). Per-user ACL — Phase 2.
- **Откат**: старый `/ws` и `/stream` работают как раньше. `NATS_ENABLED=false`
  полностью выключает мост.

## Файлы

Сервер:
- `app/nats_bridge.py` — мост (подписка `nkc.in.>`, out-воркеры, silence-guard).
- `app/routers/nats_creds.py` — `GET /nats/creds`.
- `app/ws_manager.py` — NATS-очереди в `send_to_user` + `nats_connect/disconnect`.
- `app/main.py` — lifespan моста + роутер.
- `app/config.py` — `nats_enabled/nats_url/nats_ws_user/nats_ws_pass/...`.
- `nats-server.conf` — конфиг nats-server (порты, ping, auth).
- `entrypoint.sh` — стартует nats-server и uvicorn в одном контейнере.
- `Dockerfile` — устанавливает nats-server v2.15.0 (arch определяется при сборке: amd64/arm64) + nats-py.
- `docker-compose.yml` — env NATS_* и порт `8081:8081`.
- `nekochat_cli.py` — команда `nats-ping` (проверка транспорта после деплоя).

Десктоп:
- `desktop/src/api.ts` — транспорт `"nats"` (nats.ws, автореконнект, pending-досылка).
- `desktop/src/ui/dialogs/SettingsDialog.tsx` — флаг `nc_transport=nats` в настройках.
- `desktop/package.json` — зависимость `nats.ws@^1.30.3` (deprecated, миграция на
  `@nats-io/nats-core`/nats.js 3.x — Phase 2).

## Деплой (сервер)

1. Собрать тарболл: `tar -czf nekochat-deploy.tar.gz Dockerfile docker-compose.yml
   requirements.txt entrypoint.sh nats-server.conf nginx.conf run.py app/` (без venv,
   node_modules, ssh, .token).
2. `scp nekochat-deploy.tar.gz ubuntu@100.115.20.2:~/` (ключ `ssh/komdu.key`).
3. На сервере: `bash ~/tmp/nk-deploy.sh` (или вручную
   `sudo docker compose up -d --build app` в `/home/ubuntu/nekochat`).
4. Проверить: `docker logs nekochat-app-1 --tail 50` → строки `[nats] мост подключён`,
   `[entrypoint] nats-server started` и `[entrypoint] nginx started`.
5. **Cloudflare менять НЕ нужно**: туннель так и остаётся catch-all `* → :8000`.
   Пути разруливает nginx внутри контейнера: `/nats → :8081` (nats-server, WS),
   остальное → uvicorn `:8001`. Клиент ходит на `wss://nekochat.komdu.is-cool.dev/nats`.

Переменные (compose уже содержит дефолты, но пароль стоит сменить в `.env` сервера):
```
NATS_ENABLED=true
NATS_WS_USER=nekochat
NATS_WS_PASS=<длинный случайный пароль>
```

## Проверка после деплоя

- `python nekochat_cli.py nats-ping --user Komdu --password testy --count 30 --ping-gap 2`
  — RTT по NATS-пути (ожидаем ~120-300 мс, как по /ws). Для wss-подключения локально нужен
  `pip install aiohttp` (nats-py использует aiohttp как ws-транспорт; серверу не нужен —
  мост ходит по TCP :4222). Серверный PING-вышиб (EOF) у nats-py/aiohttp — артефакт CLI,
  продакшн-клиенты (nats.ws / nats.java) отвечают на PING корректно.
- `curl https://nekochat.komdu.is-cool.dev/api/health` — приложение живо.
- `bash tmp/nk-connz.sh` (на сервере) — видно подключённых NATS-клиентов
  (монитор nats-server :8222 внутри контейнера).
- `docker logs nekochat-app-1 | grep natsDBG` — присутствие юзеров онлайн/оффлайн.

Десктоп для теста: переключить транспорт в «Соединение (тест) → NATS (WSS)» (Настройки),
перезапустить приложение. Сборка exe: `npm run tauri build` в `desktop/`.

## Откат

- Быстрый: в `docker-compose.yml` сервера `NATS_ENABLED: "false"` → пересоздать контейнер
  (`docker compose up -d app`). Все клиенты на `/ws` как раньше.
- Полный: `nk-deploy.sh` сохраняет предыдущий `app` в `app.old-<stamp>` — восстановить
  его и пересобрать.

## Phase 2 (потом)

- Per-user NATS ACL через `auth_callout` (убрать «один общий пароль»).
- Медиа (call_audio) напрямую по субъектам звонка `nkc.media.<call_id>` — без python-релея.
- Миграция десктопа с deprecated `nats.ws` на nats.js 3.x (+ browser transport).
- Выпил старых `/ws` и `/stream`, когда все клиенты на NATS.