// Транспорт: REST + WebSocket (управление) + бинарный /ws/media (аудио/видео).
//
// Перенесён из desktop/src/api.ts почти как есть — он не зависит от UI-фреймворка
// и уже проверен: ретраи с бэкоффом, heartbeat, досылка сигналов после обрыва,
// бинарные кадры без base64. Отброшено только то, чего в вебе нет и не нужно:
// NATS-транспорт, HTTP/SSE-транспорт и чтение theme.json через Tauri.

import type { AuthResult, Conversation, Msg, Room, User, WsEvent } from "./types";

/** Сколько тишины (пинги идут, ответа нет) считаем «мёртвым» соединением. */
const WS_SILENT_MS = 45000;

// ---- бинарные медиа-кадры (зеркало app/ws_media.py) ----
// 0 ver | 1 kind | 2..4 flags | 4..8 target(вверх)/from(вниз) | 8..12 length | payload
export const MK_AUDIO = 1;
export const MK_VIDEO = 2;
export const MK_FILE = 3;
export const MFLAG_ROOM = 1 << 0;
export const MFLAG_LAST = 1 << 1;
const MHDR = 12;
const MVER = 1;

/** Собрать бинарный кадр. */
export function packMedia(kind: number, flags: number, target: number, payload: Uint8Array): Uint8Array {
  const out = new Uint8Array(MHDR + payload.byteLength);
  const dv = new DataView(out.buffer);
  dv.setUint8(0, MVER);
  dv.setUint8(1, kind);
  dv.setUint16(2, flags, true);
  dv.setUint32(4, target >>> 0, true);
  dv.setUint32(8, payload.byteLength, true);
  out.set(payload, MHDR);
  return out;
}

/** Разобрать кадр. null — данных пока недостаточно, ждём остаток. */
export function unpackMedia(
  buf: ArrayBuffer,
): { kind: number; flags: number; from: number; payload: Uint8Array } | null {
  if (buf.byteLength < MHDR) return null;
  const dv = new DataView(buf);
  const ver = dv.getUint8(0);
  if (ver !== MVER) throw new Error("медиа: версия " + ver);
  const kind = dv.getUint8(1);
  const flags = dv.getUint16(2, true);
  const from = dv.getUint32(4, true);
  const len = dv.getUint32(8, true);
  const end = MHDR + len;
  if (buf.byteLength < end) return null;
  return { kind, flags, from, payload: new Uint8Array(buf, MHDR, len) };
}

export class ApiClient {
  base: string;
  token: string | null = null;
  user: User | null = null;
  meId: number | null = null;

  private ws: WebSocket | null = null;
  private wsDesired = false;
  private wsRetryTimer: number | null = null;
  private wsRetryDelay = 1000;
  private wsRetryAttempts = 0;
  private wsPingTimer: number | null = null;
  private wsOpenedAt = 0;
  private wsLastRxAt = 0;
  private wsLostFlag = false;
  /** Сигналы, отправленные в «дыру» обрыва — досылаются после открытия. */
  private wsPending: Record<string, unknown>[] = [];

  // бинарные каналы: медиа (аудио/видео) и файлы
  private wsMedia: WebSocket | null = null;
  private wsMediaDesired = false;
  private wsMediaRetryTimer: number | null = null;
  private wsMediaRetryAttempts = 0;
  private wsMediaOpenedAt = 0;
  private wsMediaLostFlag = false;

  onWs: ((ev: WsEvent) => void) | null = null;
  onWsError: ((msg: string) => void) | null = null;
  onWsLost: (() => void) | null = null;
  onWsReconnected: (() => void) | null = null;
  onAuthFailed: ((msg: string) => void) | null = null;
  onWsMedia: ((kind: number, flags: number, from: number, payload: Uint8Array) => void) | null = null;
  onWsMediaLost: (() => void) | null = null;
  onWsMediaReconnected: (() => void) | null = null;

  constructor(base?: string) {
    this.base = (base ?? window.location.origin).replace(/\/+$/, "");
  }

  // ---------------- REST ----------------

  async call<T = unknown>(method: string, path: string, payload?: unknown, auth = true): Promise<T> {
    const headers: Record<string, string> = {};
    if (payload !== undefined) headers["Content-Type"] = "application/json";
    if (auth && this.token) headers["Authorization"] = `Bearer ${this.token}`;
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
    } finally {
      window.clearTimeout(to);
    }
    let js: unknown = null;
    const text = await res.text();
    if (text) {
      try {
        js = JSON.parse(text);
      } catch {
        js = null;
      }
    }
    if (res.ok) return (js ?? {}) as T;
    const detail = (js && ((js as { detail?: unknown; error?: unknown }).detail || (js as { error?: unknown }).error)) || `HTTP ${res.status}`;
    if (res.status === 401) this.onAuthFailed?.(String(detail));
    const err = new Error(String(detail)) as Error & { server?: boolean };
    // 5xx (502/503 от Cloudflare в момент рестарта origin) — можно повторить
    if (res.status >= 500) err.server = true;
    throw err;
  }

  // ---- auth ----
  async register(username: string, password: string, displayName: string): Promise<User> {
    return this._authed(
      await this.call<AuthResult>("POST", "/auth/register", {
        username,
        password,
        display_name: displayName,
      }, false),
    );
  }

  async login(username: string, password: string): Promise<User> {
    return this._authed(await this.call<AuthResult>("POST", "/auth/login", { username, password }, false));
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

  me(): Promise<User> {
    return this.call<User>("GET", "/api/me");
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

  updateProfile(p: {
    bio?: string;
    status?: string;
    profile_color?: string;
    display_name?: string;
  }): Promise<User> {
    return this.call<User>("PUT", "/users/me/profile", p);
  }

  /** Смена пароля на свой. Старый обязателен — сервер проверяет. */
  changePassword(oldPassword: string, newPassword: string): Promise<{ ok: boolean }> {
    return this.call("PUT", "/users/me/password", {
      old_password: oldPassword,
      new_password: newPassword,
    });
  }

  /** Загрузка аватарки.
   *
   *  Отдельный метод, а не через call(): файлы уходят multipart'ом, а call()
   *  умеет только JSON. Content-Type задавать нельзя — границу проставляет
   *  сам браузер, ручной заголовок ломает разбор. */
  async uploadAvatar(file: File): Promise<User> {
    const fd = new FormData();
    fd.append("file", file, file.name || "avatar.png");
    const headers: Record<string, string> = {};
    if (this.token) headers["Authorization"] = `Bearer ${this.token}`;
    const res = await fetch(`${this.base}/users/me/avatar`, {
      method: "POST",
      headers,
      body: fd,
    });
    const text = await res.text();
    let js: unknown = null;
    if (text) {
      try {
        js = JSON.parse(text);
      } catch {
        js = null;
      }
    }
    if (!res.ok) {
      const d = (js as { detail?: unknown; error?: unknown }) ?? null;
      const detail = (d && (d.detail || d.error)) || `HTTP ${res.status}`;
      throw new Error(String(detail));
    }
    return js as User;
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

  // ---------------- WebSocket (управление) ----------------

  private nextRetryDelay(): number {
    const base = Math.min(1000 * Math.pow(2, Math.min(this.wsRetryAttempts, 2)), 4000);
    this.wsRetryAttempts++;
    return base + Math.floor(Math.random() * 300);
  }

  private clearWsRetry(): void {
    if (this.wsRetryTimer != null) {
      window.clearTimeout(this.wsRetryTimer);
      this.wsRetryTimer = null;
    }
  }

  private startWsPing(): void {
    this.stopWsPing();
    const beat = () => {
      this.wsSend({ type: "ping" });
      this.wsPingTimer = window.setTimeout(beat, 10000);
    };
    this.wsPingTimer = window.setTimeout(beat, 10000);
  }

  private stopWsPing(): void {
    if (this.wsPingTimer != null) {
      window.clearTimeout(this.wsPingTimer);
      this.wsPingTimer = null;
    }
  }

  wsOpen(reset = true): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) return;
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
      this.wsRetryAttempts = 0;
      this.wsRetryDelay = 1000;
    }
    const url = this.base.replace(/^http:/i, "ws:").replace(/^https:/i, "wss:") +
      "/ws?token=" + encodeURIComponent(this.token);
    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch {
      if (this.wsDesired) this.wsRetryTimer = window.setTimeout(() => this.wsOpen(false), this.nextRetryDelay());
      return;
    }
    this.ws = ws;
    // таймаут хендшейка: если upgrade завис (туннель принял TCP, но не довёл WS),
    // CONNECTING висел бы вечно — закрываем, onclose запустит ретрай
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
      if (this.wsLostFlag) {
        this.wsLostFlag = false;
        this.onWsReconnected?.();
      }
      // досылаем сигналы, попавшие в «дыру» (call_answer/call_hangup и пр.)
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
        if (this.wsOpenedAt) this.wsLostFlag = true;
        this.wsRetryTimer = window.setTimeout(() => this.wsOpen(false), this.nextRetryDelay());
      }
    };
    this.startWsPing();
  }

  /** readyState сокета управления. Движок звонков спрашивает это при
   *  диагностике зависшего main-thread: readyState === 1, а звука нет. */
  wsReady(): number {
    return this.ws ? this.ws.readyState : -1;
  }

  /** Сторож тишины: нет входящих дольше WS_SILENT_MS — считаем сокет мёртвым. */
  wsWatch(): void {
    if (this.ws && Date.now() - this.wsLastRxAt > WS_SILENT_MS && navigator.onLine !== false) {
      try {
        this.ws.close();
      } catch {
        /* noop */
      }
    }
  }

  wsClose(): void {
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

  private wsSend(payload: unknown): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload));
      return;
    }
    // Сокет не открыт: сигнал молча потерялся бы — для звонка это «принял, но
    // вызов упал». Запоминаем последний сигнал каждого типа и досылаем после
    // открытия.
    const kind = (payload && (payload as { type?: string }).type) || "";
    if (!kind || !this.wsDesired) return;
    this.wsPending = this.wsPending.filter((x) => (x as { type?: string }).type !== kind);
    this.wsPending.push(payload as Record<string, unknown>);
    if (this.wsPending.length > 8) this.wsPending.shift();
    if (!this.ws) this.wsOpen();
  }

  /** Сигналинг и текст — по /ws. */
  send(payload: Record<string, unknown>): void {
    this.wsSend(payload);
  }

  sendRoom(roomId: number, content: string): void {
    this.wsSend({ type: "room_message", room_id: roomId, content });
  }

  sendDm(toId: number, content: string): void {
    this.wsSend({ type: "direct_message", to_id: toId, content });
  }

  sendCallSignal(payload: Record<string, unknown>): void {
    this.wsSend(payload);
  }

  // ---------------- бинарный медиа-сокет ----------------

  private mediaUrl(channel: "media" | "transfer"): string {
    return (
      this.base.replace(/^http:/i, "ws:").replace(/^https:/i, "wss:") +
      "/ws/" + channel + "?token=" + encodeURIComponent(this.token || "")
    );
  }

  wsMediaOpen(channel: "media" | "transfer" = "media", reset = true): void {
    const cur = channel === "transfer" ? this.wsTransfer : this.wsMedia;
    if (cur && cur.readyState === WebSocket.OPEN) return;
    if (cur) {
      try {
        cur.onclose = null;
        cur.close();
      } catch {
        /* noop */
      }
      if (channel === "transfer") this.wsTransfer = null;
      else this.wsMedia = null;
    }
    if (!this.token) {
      this.wsMediaDesired = false;
      return;
    }
    this.wsMediaDesired = true;
    this.clearMediaRetry();
    if (reset) this.wsMediaRetryAttempts = 0;
    let ws: WebSocket;
    try {
      ws = new WebSocket(this.mediaUrl(channel));
    } catch {
      this.scheduleMediaRetry(channel);
      return;
    }
    ws.binaryType = "arraybuffer";
    if (channel === "transfer") this.wsTransfer = ws;
    else this.wsMedia = ws;
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
      this.wsMediaOpenedAt = Date.now();
      if (this.wsMediaLostFlag) {
        this.wsMediaLostFlag = false;
        this.onWsMediaReconnected?.();
      }
    };
    ws.onmessage = (e) => {
      if (typeof e.data === "string") return;
      try {
        const f = unpackMedia(e.data as ArrayBuffer);
        if (f) this.onWsMedia?.(f.kind, f.flags, f.from, f.payload);
      } catch {
        /* мусорный кадр */
      }
    };
    ws.onerror = () => {
      /* onclose отработает следом */
    };
    ws.onclose = () => {
      window.clearTimeout(hsTimer);
      if (this.wsMedia === ws) this.wsMedia = null;
      if (this.wsTransfer === ws) this.wsTransfer = null;
      if (this.wsMediaOpenedAt) this.wsMediaLostFlag = true;
      this.onWsMediaLost?.();
      if (this.wsMediaDesired) this.scheduleMediaRetry(channel);
    };
  }

  private wsTransfer: WebSocket | null = null;

  private scheduleMediaRetry(channel: "media" | "transfer"): void {
    if (this.wsMediaRetryTimer != null) return;
    const base = Math.min(1000 * Math.pow(2, Math.min(this.wsMediaRetryAttempts, 2)), 4000);
    this.wsMediaRetryAttempts++;
    this.wsMediaRetryTimer = window.setTimeout(() => {
      this.wsMediaRetryTimer = null;
      this.wsMediaOpen(channel, false);
    }, base + Math.floor(Math.random() * 300));
  }

  private clearMediaRetry(): void {
    if (this.wsMediaRetryTimer != null) {
      window.clearTimeout(this.wsMediaRetryTimer);
      this.wsMediaRetryTimer = null;
    }
  }

  wsMediaClose(): void {
    this.wsMediaDesired = false;
    this.clearMediaRetry();
    for (const ws of [this.wsMedia, this.wsTransfer]) {
      if (ws) {
        try {
          ws.onclose = null;
          ws.close();
        } catch {
          /* noop */
        }
      }
    }
    this.wsMedia = null;
    this.wsTransfer = null;
  }

  /** Отправить бинарный кадр. false — сокет не готов (фолбэк на /ws или дроп). */
  sendMedia(kind: number, flags: number, target: number, payload: Uint8Array): boolean {
    const ws = this.wsMedia;
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    try {
      ws.send(packMedia(kind, flags, target, payload));
      return true;
    } catch {
      return false;
    }
  }

  get mediaReady(): boolean {
    return !!this.wsMedia && this.wsMedia.readyState === WebSocket.OPEN;
  }
}
