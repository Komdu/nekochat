#!/bin/sh
# Один контейнер = nats-server (транспорт клиентов) + nginx (разводка путей) + приложение.
set -e
nats-server -c /app/nats-server.conf &
echo "[entrypoint] nats-server started (pid $!)"
nginx -g 'daemon off;' &
echo "[entrypoint] nginx started (pid $!)"
exec python run.py