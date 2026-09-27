FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# nats-server — транспорт клиентов (Phase 1). Бинарь статический; архитектуру
# определяем во время сборки (на сервере может быть amd64 или arm64).
ENV NATS_SERVER_VERSION=2.15.0
RUN apt-get update \
    && apt-get install -y --no-install-recommends wget ca-certificates \
    && NATS_ARCH="$(uname -m)"; case "$NATS_ARCH" in \
         x86_64|amd64) NATS_ARCH=amd64 ;; \
         aarch64|arm64) NATS_ARCH=arm64 ;; \
         *) echo "unsupported arch: $NATS_ARCH"; exit 1 ;; \
       esac; \
    wget -qO /tmp/nats.tar.gz https://github.com/nats-io/nats-server/releases/download/v${NATS_SERVER_VERSION}/nats-server-v${NATS_SERVER_VERSION}-linux-${NATS_ARCH}.tar.gz \
    && tar -xzf /tmp/nats.tar.gz -C /tmp \
    && mv /tmp/nats-server-v${NATS_SERVER_VERSION}-linux-${NATS_ARCH}/nats-server /usr/local/bin/nats-server \
    && rm -rf /tmp/nats* \
    && apt-get purge -y wget \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# nginx — фронт контейнера: /nats → nats-server (:8081), остальное → uvicorn (:8001).
# Пути разруливаем на сервере, а не в Cloudflare (там catch-all на :8000).
RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx-light \
    && rm -f /etc/nginx/sites-enabled/default \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY nginx.conf /etc/nginx/nginx.conf

EXPOSE 8000 4222 8081

CMD ["sh", "/app/entrypoint.sh"]