// Порт client_ui/api.py: REST (fetch) + WebSocket, без Qt.
import type { AuthResult, Msg, Room, User, Conversation, WsEvent } from "./types";
import * as nats from "nats.ws";

/** Сколько времени полной тишины (наши пинги идут, ответа нет) считаем «мёртвым» соединением. */
const WS_SILENT_MS = 45000;

export class ApiClient {
  base: string;
  token: string | null = null;
  user: User | null = null;
  meId: number | null = null;
  /** Транспорт реального времени: "ws" (по умолчанию), "http" (SSE+POST) или "nats" (Phase 1).
   *  Переключение — localStorage: localStorage.setItem("nc_transport","nats") */
  transport: "ws" | "http" | "nats" = "ws";
  private ws: WebSocket | null = null;
  private nc: nats.NatsConnection | null = null;
  private natsSub: nats.Subscription | null = null;
  private natsUid = 0;
  private natsOpening = false;
  private es: EventSource | null = null;
  private httpReady = false;
  private httpPending: Record<string, unknown>[] = [];
  private wsDesired = false; // хотим держать соединение открытым (false — намеренное закрытие/логаут)
  private wsRetryTimer: number | null = null;
  private wsRetryDelay = 1000;
  private wsRetryAttempts = 0;
  private wsPingTimer: number | null = null;
  private wsOpenedAt = 0;
  private wsLastRxAt = 0;
  private wsLostFlag = false; // был обрыв — при следующем onopen нужно досинхронизировать
  /** Сигналы, отправленные, когда сокет был не OPEN (обрыв/переподключение) — досылаются после открытия */
  private wsPending: Record<string, unknown>[] = [];
  onWs: ((ev: WsEvent) => void) | null = null;
  onWsError: ((msg: string) => void) | null = null;
  onWsLost: (() => void) | null = null;
  onWsReconnected: (() => void) | null = null;
  onAuthFailed: ((msg: string) => void) | null = null;

  constructor(base: string) {
    this.base = base.replace(/\/+$/, "");
    // Раньше здесь можно было переключиться на "http" (SSE+POST) и "nats" (Phase 1)
    // через localStorage nc_transport — по решению владельца эти транспорты удалены:
    // работаем только на классическом WebSocket (/ws). Локальную настройку игнорируем.
  }

  // ---------------- REST ----------------

  async call<T = unknown>(method: string, path: string, payload?: unknown, auth = true): Promise<T> {
    const headers: Record<string, string> = {};
    if (payload !== undefined) headers["Content-Type"] = "application/json";
    if (auth && this.token) headers["Authorization"] = `Bearer ${this.token}`;
    // таймаут: зависший запрос (туннель/сеть) не должен вешать клиент навсегда.
    // fetch без signal ждёт ответа бесконечно — а у нас нет лимита на стороне сервера.
    const controller = new AbortController();
    const to = window.setTimeout(() => controller.abort(), 15000);
    let res: Response;
    try {
      res = await fetch(this.base + path, {
        method,
        headers,
        body: payload !== undefined ? JSON.stringify(payload) : undefined,
        signal: controller.signal,
      });
    } catch (e) {
      // сетевой сбой или таймаут — такой запрос безопасно повторить
      const err = new Error("Нет соединения с сервером") as Error & { network?: boolean };
      err.network = true;
      throw err;
    } finally {
      window.clearTimeout(to);
    }
    let js: any = null;
    const text = await res.text();
    if (text) {
      try {
        js = JSON.parse(text);
      } catch {
        js = null;
      }
    }
    if (res.ok) return (js ?? {}) as T;
    const detail = (js && (js.detail || js.error)) || `HTTP ${res.status}`;
    if (res.status === 401) this.onAuthFailed?.(String(detail));
    // 5xx (например, 502/503 от Cloudflare в момент рестарта origin) — можно повторить
    const err = new Error(String(detail)) as Error & { server?: boolean };
    if (res.status >= 500) err.server = true;
    throw err;
  }

  // ---- auth ----
  async register(username: string, password: string, displayName: string): Promise<User> {
    const js = await this.call<AuthResult>("POST", "/auth/register", {
      username,
      password,
      display_name: displayName,
    }, false);
    return this._authed(js);
  }

  async login(username: string, password: string): Promise<User> {
    const js = await this.call<AuthResult>("POST", "/auth/login", { username, password }, false);
    return this._authed(js);
  }

  private _authed(js: AuthResult): User {
    const tok = js && js.access_token;
    const user = js && js.user;
    if (tok && user && typeof user === "object") {
      this.token = tok;
      this.user = user;
      this.meId = user.id;
      return user;
    }
    throw new Error("Ошибка авторизации: пустой ответ");
  }

  // ---- профиль / люди ----
  async me(): Promise<User> {
    const js = await this.call<User>("GET", "/api/me");
    this.user = js;
    this.meId = js && typeof js === "object" ? (js as any).id : this.meId;
    this.onWsError?.("");
    return js;
  }

  users(): Promise<User[]> {
    return this.call<User[]>("GET", "/users");
  }

  conversations(): Promise<Conversation[]> {
    return this.call<Conversation[]>("GET", "/users/conversations/me");
  }

  dmMessages(otherId: number): Promise<Msg[]> {
    return this.call<Msg[]>("GET", `/users/${otherId}/messages`);
  }

  updateProfile(p: { bio?: string; status?: string; profile_color?: string }): Promise<unknown> {
    return this.call("PUT", "/users/me/profile", p);
  }

  async uploadAvatar(file: File): Promise<unknown> {
    const form = new FormData();
    form.append("file", file, file.name);
    const res = await fetch(this.base + "/users/me/avatar", {
      method: "POST",
      headers: this.token ? { Authorization: `Bearer ${this.token}` } : {},
      body: form,
    });
    let js: any = null;
    const text = await res.text();
    if (text) {
      try {
        js = JSON.parse(text);
      } catch {
        js = null;
      }
    }
    if (res.ok) return js ?? {};
    const detail = (js && (js.detail || js.error)) || `HTTP ${res.status}`;
    if (res.status === 401) this.onAuthFailed?.(String(detail));
    throw new Error(String(detail));
  }

  // ---- комнаты ----
  rooms(): Promise<Room[]> {
    return this.call<Room[]>("GET", "/rooms");
  }

  createRoom(name: string): Promise<Room> {
    return this.call<Room>("POST", "/rooms", { name });
  }

  joinRoom(roomId: number): Promise<unknown> {
    return this.call("POST", `/rooms/${roomId}/join`, {});
  }

  addMember(roomId: number, username: string): Promise<unknown> {
    return this.call("POST", `/rooms/${roomId}/members`, { username });
  }

  roomMessages(roomId: number): Promise<Msg[]> {
    return this.call<Msg[]>("GET", `/rooms/${roomId}/messages`);
  }

  avatarUrl(filename: string): string {
    return `${this.base}/avatars/${encodeURIComponent(filename)}`;
  }

  health(): Promise<unknown> {
    return this.call("GET", "/api/health", undefined, false);
  }

  // ---------------- WS / HTTP transport ----------------
  wsOpen(reset = true): void {
    if (this.transport === "http") {
      this.httpOpen();
      return;
    }
    if (this.transport === "nats") {
      void this.natsOpen();
      return;
    }
    // уже открыт — не трогаем (focus-обработчик не должен рвать живое соединение)
    if (this.ws && this.ws.readyState === WebSocket.OPEN) return;
    // закрыть старый сокет, не трогая намерение wsDesired (сюда приходим и из ретрая)
    if (this.ws) {
      try {
        this.ws.onclose = null;
        this.ws.close();
      } catch {
        /* noop */
      }
      this.ws = null;
    }
    if (!this.token) {
      this.wsDesired = false;
      return;
    }
    this.wsDesired = true;
    this.clearWsRetry();
    if (reset) {
      // свежий запуск/пользовательская попытка — бэкофф с нуля;
      // ретрай-путь (reset=false) бэкофф не сбрасывает, иначе он не растёт
      this.wsRetryAttempts = 0;
      this.wsRetryDelay = 1000;
    }
    const url =
      this.base.replace(/^http:/i, "ws:").replace(/^https:/i, "wss:") +
      "/ws?token=" + encodeURIComponent(this.token);
    try {
      const ws = new WebSocket(url);
      this.ws = ws;
      // таймаут хендшейка: если upgrade завис (туннель принял TCP, но не довёл WS),
      // CONNECTING висел бы вечно — закрываем, onclose запустит ретрай.
      const hsTimer = window.setTimeout(() => {
        if (ws.readyState === WebSocket.CONNECTING) {
          try {
            ws.close();
          } catch {
            /* noop */
          }
        }
      }, 10000);
      ws.onopen = () => {
        window.clearTimeout(hsTimer);
        this.wsOpenedAt = Date.now();
        this.wsLastRxAt = Date.now();
        // «дыра» закончилась: после обрыва досинхронизируемся (presence/списки)
        if (this.wsLostFlag) {
          this.wsLostFlag = false;
          this.onWsReconnected?.();
        }
        // досылаем сигналы, попавшие в «дыру» переподключения (call_answer/call_hangup и пр.)
        const pending = this.wsPending;
        this.wsPending = [];
        for (const p of pending) {
          try {
            ws.send(JSON.stringify(p));
          } catch {
            /* noop */
          }
        }
      };
      ws.onmessage = (e) => {
        // любое входящее (pong/событие) — признак живого соединения
        this.wsLastRxAt = Date.now();
        let m: WsEvent | null = null;
        try {
          m = JSON.parse(String(e.data));
        } catch {
          m = null;
        }
        if (m && typeof m === "object") this.onWs?.(m);
      };
      ws.onerror = () => this.onWsError?.("WS: ошибка соединения");
      ws.onclose = () => {
        window.clearTimeout(hsTimer);
        if (this.ws === ws) this.ws = null;
        this.stopWsPing();
        this.onWsLost?.();
        if (this.wsDesired) {
          // были живы — значит, обрыв, а не первый коннект: при onopen досинхронизируемся
          if (this.wsOpenedAt) this.wsLostFlag = true;
          // переподключаемся с экспоненциальным бэкоффом + джиттером (1с → ~15с)
          this.onWsError?.("WS: закрыто — переподключение…");
          this.wsRetryTimer = window.setTimeout(() => this.wsOpen(false), this.nextRetryDelay());
        } else {
          this.onWsError?.("WS: закрыто");
        }
      };
      this.startWsPing();
    } catch (e) {
      this.onWsError?.("WS: не удалось открыть");
      if (this.wsDesired) {
        this.wsRetryTimer = window.setTimeout(() => this.wsOpen(false), this.nextRetryDelay());
      }
    }
  }

  wsClose(): void {
    if (this.transport === "http") {
      this.httpClose();
      return;
    }
    if (this.transport === "nats") {
      this.natsClose();
      return;
    }
    this.wsDesired = false;
    this.clearWsRetry();
    this.stopWsPing();
    this.wsPending = [];
    if (this.ws) {
      try {
        this.ws.onclose = null;
        this.ws.close();
      } catch {
        /* noop */
      }
      this.ws = null;
    }
  }

  /** Клиентский heartbeat: шлём ping каждые 10с, чтобы соединение не резали по простою
   *  (Cloudflare edge ~100с, разные прокси). Это data-кадр — проходит сквозь туннель. */
  private startWsPing(): void {
    this.stopWsPing();
    this.wsPingTimer = window.setInterval(() => {
      if (this.transport === "nats") {
        // NATS: прикладной ping нужен серверу для presence (мост считает online по трафику)
        this.natsSend({ type: "ping" });
        return;
      }
      const ws = this.ws;
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      const now = Date.now();
      // «тихая смерть»: браузер не даёт onclose на оборванном TCP (туннель/Cloudflare/NAT) —
      // сокет висит в OPEN вечно. Если при наших пингах (раз в 10с) сервер молчит целую
      // минуту — соединение мертво/туннель застрял; рвём сами, onclose поднимет реконнект.
      // Минута тишины не ложно-сработает на медленном туннеле в отличие от счёта пингов.
      if (now - this.wsLastRxAt > WS_SILENT_MS && navigator.onLine !== false) {
        this.onWsError?.("WS: нет трафика от сервера — переподключение…");
        try {
          ws.close(4000, "no-traffic");
        } catch {
          /* noop */
        }
        return;
      }
      try {
        ws.send(JSON.stringify({ type: "ping" }));
      } catch {
        /* noop */
      }
    }, 10000);
  }

  private stopWsPing(): void {
    if (this.wsPingTimer != null) {
      window.clearInterval(this.wsPingTimer);
      this.wsPingTimer = null;
    }
  }

  private clearWsRetry(): void {
    if (this.wsRetryTimer != null) {
      window.clearTimeout(this.wsRetryTimer);
      this.wsRetryTimer = null;
    }
  }

  /** Быстрый бэкофф с джиттером: 1с → 2с → 4с (потолок) + до 300мс рандома.
   *  Туннель рвёт WS периодически (edge ~2 мин) — долгая экспонента даёт
   *  длинные «мёртвые» окна, поэтому рост почти сразу упирается в 4с. */
  private nextRetryDelay(): number {
    const base = Math.min(1000 * Math.pow(2, Math.min(this.wsRetryAttempts, 2)), 4000);
    this.wsRetryAttempts++;
    return base + Math.floor(Math.random() * 300);
  }

  private wsSend(payload: unknown): void {
    if (this.transport === "http") {
      this.httpSend(payload as Record<string, unknown>);
      return;
    }
    if (this.transport === "nats") {
      this.natsSend(payload);
      return;
    }
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload));
      return;
    }
    // Сокет не открыт (момент обрыва/переподключения): раньше сигнал молча терялся —
    // для звонка это означало «принял, но вызов упал». Запоминаем последний сигнал
    // каждого типа и досылаем после открытия (см. ws.onopen).
    const kind = (payload && (payload as { type?: string }).type) || "";
    if (!kind || !this.wsDesired) return;
    this.wsPending = this.wsPending.filter((x) => (x as { type?: string }).type !== kind);
    this.wsPending.push(payload as Record<string, unknown>);
    if (this.wsPending.length > 8) this.wsPending.shift();
    // если сокета нет вовсе — форсируем переподключение (CONNECTING уже в процессе — не трогаем)
    if (!this.ws) this.wsOpen();
  }

  // ---------------- NATS transport (Phase 1) ----------------
  /** Подключение через nats-server (wss://host/nats). Креды берём у REST /nats/creds.
   *  nats.ws сам переподключается (reconnect + maxReconnectAttempts=-1), поэтому
   *  ретрай тут — только на старте/ошибке креда; pending-сигналы досылаем сами. */
  private async natsOpen(): Promise<void> {
    if (this.nc && !this.nc.isClosed()) return;
    if (this.natsOpening || !this.token) {
      this.wsDesired = !!this.token;
      return;
    }
    this.natsOpening = true;
    this.wsDesired = true;
    this.clearWsRetry();
    this.wsRetryDelay = 1000;
    try {
      const c = await this.call<{ url: string; user: string; password: string; uid: number; ping: number }>(
        "GET",
        "/nats/creds"
      );
      if (!c.url || !c.user || !c.password || !c.uid) throw new Error("bad nats creds");
      const nc = await nats.connect({
        servers: [c.url],
        user: c.user,
        pass: c.password,
        name: "nekochat-desktop",
        reconnect: true,
        maxReconnectAttempts: -1,
        reconnectTimeWait: 1000,
        pingInterval: (c.ping || 10) * 1000,
        maxPingOut: 2,
        timeout: 10000,
      });
      if (!this.wsDesired) {
        // успели разлогиниться во время коннекта
        try {
          await nc.close();
        } catch {
          /* noop */
        }
        this.natsOpening = false;
        return;
      }
      this.nc = nc;
      this.natsUid = c.uid;
      try {
        (async () => {
          try {
            for await (const st of nc.status()) {
              const t = (st && st.type) || "";
              if (t === "disconnect" || t === "reconnecting") this.onWsLost?.();
              if (t === "disconnect") this.onWsError?.("NATS: соединение потеряно");
              if (t === "reconnect") this.onWsError?.("NATS: переподключился");
              if (t === "error") this.onWsError?.("NATS: ошибка соединения");
            }
          } catch {
            /* noop */
          }
        })();
      } catch {
        /* noop */
      }
      this.natsSub = nc.subscribe(`nkc.out.${c.uid}`);
      (async () => {
        for await (const m of this.natsSub!) {
          let ev: WsEvent | null = null;
          try {
            ev = JSON.parse(new TextDecoder().decode(m.data));
          } catch {
            ev = null;
          }
          if (ev && typeof ev === "object") this.onWs?.(ev);
        }
      })();
      // пингуем сразу (сервер отметит online) и досылаем pending-сигналы
      const pending = this.wsPending;
      this.wsPending = [];
      this.natsSend({ type: "ping" });
      for (const p of pending) this.natsSend(p);
      this.startWsPing();
    } catch (e) {
      this.onWsError?.("NATS: не удалось подключиться");
      if (this.nc) {
        try {
          await this.nc.close();
        } catch {
          /* noop */
        }
        this.nc = null;
      }
      if (this.wsDesired) {
        this.wsRetryTimer = window.setTimeout(() => void this.natsOpen(), this.wsRetryDelay);
        this.wsRetryDelay = Math.min(this.wsRetryDelay * 2, 15000);
      }
    } finally {
      this.natsOpening = false;
    }
  }

  private natsClose(): void {
    this.wsDesired = false;
    this.clearWsRetry();
    this.stopWsPing();
    this.wsPending = [];
    this.natsSub = null;
    if (this.nc) {
      try {
        void this.nc.close();
      } catch {
        /* noop */
      }
      this.nc = null;
    }
  }

  /** Отправка в nkc.in.<uid>. При обрыве — в pending (тот же механизм, что и у WS). */
  private natsSend(payload: unknown): void {
    if (this.nc && !this.nc.isClosed() && this.natsUid) {
      try {
        this.nc.publish(`nkc.in.${this.natsUid}`, JSON.stringify(payload));
        return;
      } catch {
        /* fallthrough */
      }
    }
    const kind = (payload && (payload as { type?: string }).type) || "";
    if (!kind || !this.wsDesired) return;
    this.wsPending = this.wsPending.filter((x) => (x as { type?: string }).type !== kind);
    this.wsPending.push(payload as Record<string, unknown>);
    if (this.wsPending.length > 8) this.wsPending.shift();
    if (!this.nc && !this.natsOpening) void this.natsOpen();
  }

  // ---------------- HTTP transport (SSE + POST) ----------------
  /** SSE-поток входящих событий. EventSource сам переподключается, поэтому onerror
   *  только сигнализирует о потере, а ручной ретрай не нужен (в отличие от WS). */
  private httpOpen(): void {
    // уже открыт или подключается — EventSource сам доведёт (onopen выставит httpReady)
    if (this.es && this.es.readyState !== EventSource.CLOSED) return;
    if (!this.token) {
      this.wsDesired = false;
      return;
    }
    this.wsDesired = true;
    this.clearWsRetry();
    this.wsRetryDelay = 1000;
    const url = this.base + "/stream?token=" + encodeURIComponent(this.token);
    try {
      const es = new EventSource(url);
      this.es = es;
      es.onopen = () => {
        this.httpReady = true;
        // досылаем сигналы, попавшие в «дыру» переподключения
        const pending = this.httpPending;
        this.httpPending = [];
        for (const p of pending) this.httpSend(p);
      };
      es.onmessage = (e) => {
        let m: WsEvent | null = null;
        try {
          m = JSON.parse(String(e.data));
        } catch {
          m = null;
        }
        if (m && typeof m === "object") this.onWs?.(m);
      };
      es.onerror = () => {
        this.httpReady = false;
        this.onWsLost?.();
      };
    } catch (e) {
      this.onWsError?.("HTTP: не удалось открыть поток");
      if (this.wsDesired) {
        this.wsRetryTimer = window.setTimeout(() => this.httpOpen(), this.wsRetryDelay);
        this.wsRetryDelay = Math.min(this.wsRetryDelay * 2, 15000);
      }
    }
  }

  private httpClose(): void {
    this.wsDesired = false;
    this.clearWsRetry();
    this.httpPending = [];
    this.httpReady = false;
    if (this.es) {
      try {
        this.es.close();
      } catch {
        /* noop */
      }
      this.es = null;
    }
  }

  /** Исходящее событие: POST /push (аудио-пачки шлём по одному запросу — HTTP/2 мультиплексирует). */
  private httpSend(payload: Record<string, unknown>): void {
    if (!this.httpReady) {
      const kind = String((payload as { type?: unknown }).type ?? "");
      if (!kind || !this.wsDesired) return;
      this.httpPending = this.httpPending.filter((x) => String((x as { type?: unknown }).type) !== kind);
      this.httpPending.push(payload);
      if (this.httpPending.length > 8) this.httpPending.shift();
      if (!this.es) this.httpOpen();
      return;
    }
    this.call("POST", "/push", payload).catch(() => undefined);
  }

  /** Текущий readyState транспорта (для диагностики) или -1, если соединения нет. */
  wsReady(): number {
    if (this.transport === "http") {
      return this.es ? this.es.readyState : -1;
    }
    if (this.transport === "nats") {
      if (this.nc && !this.nc.isClosed()) return 1; // WebSocket.OPEN-эквивалент
      return this.natsOpening ? 0 : -1;
    }
    return this.ws ? this.ws.readyState : -1;
  }

  /** Ответ на серверный ping — держит WS живым. (HTTP-транспорт: SSE самодержится keepalive'ами.) */
  wsPong(): void {
    if (this.transport === "http") return;
    this.wsSend({ type: "pong" });
  }

  sendRoom(roomId: number | string, content: string): void {
    this.wsSend({ type: "room_message", room_id: roomId, content });
  }

  sendDm(toId: number, content: string): void {
    this.wsSend({ type: "direct_message", to_id: toId, content });
  }

  /** Сигналинг и аудио звонка — сервер релеит (call-типы / call_audio по WS). */
  sendCallSignal(payload: Record<string, unknown>): void {
    this.wsSend(payload);
  }
}