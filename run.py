"""Launch uvicorn behind nginx (single-container front splits paths:

  /nats  -> nats-server :8081 (NATS over WSS)
  all    -> this app       :8001

Cloudflare tunnel stays a simple catch-all to :8000 (nginx), no dashboard
routing required. uvicorn binds 127.0.0.1 only.

WebSocket keepalive pings are disabled: Cloudflare's edge/cloudflared does not
reliably relay WS protocol-level ping/pong, so uvicorn's default keepalive
(ping every 20s, close after 20s without pong) kills healthy idle connections
every ~20-40s. Liveness is application-level: clients send {"type":"ping"}
every 10s, the server answers {"type":"pong"} — ordinary data frames that pass
through the tunnel.

proxy_headers=True: trust X-Forwarded-Proto/Host from nginx/cloudflared so
request.url.scheme is https and /nats/creds returns a correct wss:// url.
"""
import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "8001")),
        proxy_headers=True,
        ws_ping_interval=None,
        ws_ping_timeout=None,
        ws_max_size=64 * 1024 * 1024,
    )