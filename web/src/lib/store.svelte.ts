// Состояние приложения на runes (Svelte 5).
//
// Логика перенесена из desktop/src/store.tsx, но без React: здесь $state/$derived
// вместо useState/useEffect, а реактивность обеспечивает сам рантайм. WS-логика
// (heartbeat, ретраи, ре-анонс канала) сохранена один в один — она проверена.

import { ApiClient } from "./net";
import { CallEngine, type CallState } from "./calls";
import { pluralized } from "./format";
import type { Conversation, Current, Msg, Room, User, WsEvent } from "./types";

const LS = {
  token: "nk.token",
  user: "nk.user",
  last: "nk.last",
};

export type Phase = "boot" | "login" | "ready";

function loadJson<T>(key: string, def: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : def;
  } catch {
    return def;
  }
}

function saveJson(key: string, v: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(v));
  } catch {
    /* приватный режим — молча */
  }
}

class Store {
  phase = $state<Phase>("boot");
  me = $state<User | null>(null);
  rooms = $state<Room[]>([]);
  convs = $state<Conversation[]>([]);
  users = $state<User[]>([]);
  usersMap = $state<Record<number, User>>({});
  online = $state<Set<number>>(new Set());
  current = $state<Current | null>(null);
  msgs = $state<Record<string, Msg[]>>({});
  note = $state("");
  busy = $state(false);
  error = $state("");

  /** Состояние звонка для UI. null — звонка нет (или он закрыт). */
  call = $state<CallState | null>(null);

  api = new ApiClient();
  base = this.api.base;

  private noteTimer: number | null = null;
  private seen: Record<string, Set<string | number>> = {};
  private watchTimer: number | null = null;
  /** Движок звонков. Создаётся, когда известен наш id (после логина). */
  calls: CallEngine | null = null;

  constructor() {
    this.wire();
    void this.boot();
  }

  // ---------------- производные ----------------
  get list(): Array<{ kind: "room" | "dm"; id: string; label: string; sub: string }> {
    const out: Array<{ kind: "room" | "dm"; id: string; label: string; sub: string }> = [];
    for (const r of this.rooms) {
      const n = r.member_count ?? r.members?.length ?? 0;
      out.push({
        kind: "room",
        id: String(r.id),
        label: r.name,
        sub: pluralized(n, "участник", "участника", "участников"),
      });
    }
    const meId = this.me?.id;
    for (const u of this.users) {
      if (u.id === meId) continue;
      out.push({ kind: "dm", id: String(u.id), label: u.display_name || u.username, sub: "@" + u.username });
    }
    return out;
  }

  get messages(): Msg[] {
    const cur = this.current;
    return cur ? this.msgs[cur.key] || [] : [];
  }

  /** Сколько человек сейчас на связи. Считаем по событиям presence, а не по
   *  размеру списка пользователей — тот включает и тех, кто давно не заходил. */
  get onlineCount(): number {
    return Math.max(1, this.online.size);
  }

  isOnline(u: { id: number } | null | undefined): boolean {
    return !!u && (this.online.has(u.id) || !!this.usersMap[u.id]?.is_online);
  }

  // ---------------- уведомления ----------------
  noteMsg(m: string): void {
    this.note = m;
    if (this.noteTimer != null) window.clearTimeout(this.noteTimer);
    if (m) this.noteTimer = window.setTimeout(() => (this.note = ""), 6000);
  }

  // ---------------- вход / регистрация ----------------
  async login(username: string, password: string): Promise<void> {
    this.busy = true;
    this.error = "";
    try {
      const user = await this.api.login(username, password);
      this.afterAuth(user);
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
      throw e;
    } finally {
      this.busy = false;
    }
  }

  async register(username: string, password: string, display: string): Promise<void> {
    this.busy = true;
    this.error = "";
    try {
      const user = await this.api.register(username, password, display);
      this.afterAuth(user);
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
      throw e;
    } finally {
      this.busy = false;
    }
  }

  private afterAuth(user: User): void {
    localStorage.setItem(LS.token, this.api.token || "");
    saveJson(LS.user, user);
    this.me = user;
    this.phase = "ready";
    this.api.wsOpen();
    this.api.wsMediaOpen("media");
    this.ensureCalls(user.id);
    void this.loadData();
  }

  // ---------------- звонки ----------------

  /** Создать движок звонков. Один на сессию: при смене пользователя —
   *  старый уничтожается (иначе остались бы открытые микрофон и AudioContext). */
  private ensureCalls(meId: number): void {
    this.calls?.destroy();
    const engine = new CallEngine(meId, (m) => this.api.sendCallSignal(m));
    engine.wsStateGetter = () => this.api.wsReady();
    // аудио/видео — в бинарный сокет; sendMedia вернёт false, если он не готов
    engine.mediaSink = (kind, flags, target, payload) => this.api.sendMedia(kind, flags, target, payload);
    engine.onState = (s) => {
      // «ended» показываем, чтобы пользователь увидел причину, дальше — тишина
      this.call = s.phase === "idle" ? null : s;
    };
    this.calls = engine;
  }

  callPeer(u: User): void {
    void this.calls?.start(u.id);
  }

  joinRoomCall(roomId: number): void {
    void this.calls?.startRoomCall(roomId);
  }

  logout(): void {
    this.calls?.destroy();
    this.calls = null;
    this.call = null;
    this.api.wsMediaClose();
    this.api.wsClose();
    this.me = null;
    this.rooms = [];
    this.convs = [];
    this.users = [];
    this.usersMap = {};
    this.online = new Set();
    this.current = null;
    this.msgs = {};
    this.seen = {};
    localStorage.removeItem(LS.token);
    localStorage.removeItem(LS.user);
    this.phase = "login";
  }

  private async boot(): Promise<void> {
    const token = localStorage.getItem(LS.token);
    const saved = loadJson<User | null>(LS.user, null);
    if (!token || !saved) {
      this.phase = "login";
      return;
    }
    this.api.token = token;
    this.api.user = saved;
    this.api.meId = saved.id;
    this.me = saved;
    this.phase = "ready";
    this.api.wsOpen();
    this.api.wsMediaOpen("media");
    this.ensureCalls(saved.id);
    // сервер мог перезапуститься / туннель моргнул — пробуем несколько раз
    const attempt = async (n: number): Promise<void> => {
      try {
        const me = await this.api.me();
        this.me = me;
        saveJson(LS.user, me);
        await this.loadData();
      } catch (e) {
        const err = e as { server?: boolean; network?: boolean; message?: string };
        if (n < 3 && (err.server || err.network)) {
          await new Promise((r) => setTimeout(r, 700 * n));
          return attempt(n + 1);
        }
        this.logout();
      }
    };
    await attempt(1);
  }

  private async loadData(): Promise<void> {
    try {
      const [rs, us, cs] = await Promise.all([this.api.rooms(), this.api.users(), this.api.conversations()]);
      const meId = this.api.meId;
      this.rooms = Array.isArray(rs) ? rs : [];
      this.users = (Array.isArray(us) ? us : []).filter((u) => u.id !== meId);
      this.convs = Array.isArray(cs) ? cs : [];
      const map: Record<number, User> = {};
      for (const r of this.rooms) for (const m of r.members || []) if (m?.id != null) map[m.id] = { ...map[m.id], ...m };
      for (const u of this.users) map[u.id] = { ...map[u.id], ...u };
      for (const c of this.convs) if (c.user?.id != null) map[c.user.id] = { ...map[c.user.id], ...c.user };
      this.usersMap = map;
      if (!this.current) {
        // открываем последний чат, а если его нет — первую комнату: пустой
        // правый экран после входа выглядит как «ничего не работает»
        const last = loadJson<{ kind: string; id: string } | null>(LS.last, null);
        const r = last?.kind === "room" ? this.rooms.find((x) => String(x.id) === last.id) : undefined;
        const target = r ?? this.rooms[0];
        if (target) void this.selectRoom(target);
      }
    } catch (e) {
      this.noteMsg(e instanceof Error ? e.message : String(e));
    }
  }

  // ---------------- выбор чата ----------------
  selectRoom(r: Room): void {
    const key = "room/" + String(r.id);
    this.current = { kind: "room", id: String(r.id), key, label: "# " + r.name };
    saveJson(LS.last, { kind: "room", id: String(r.id) });
    void this.openHistory(key, () => this.api.roomMessages(Number(r.id)));
  }

  selectUser(u: User): void {
    const key = "dm/" + String(u.id);
    this.current = { kind: "dm", id: String(u.id), key, label: "@ " + (u.display_name || u.username) };
    this.usersMap = { ...this.usersMap, [u.id]: { ...this.usersMap[u.id], ...u } };
    saveJson(LS.last, { kind: "dm", id: u.id });
    void this.openHistory(key, () => this.api.dmMessages(u.id));
  }

  private async openHistory(key: string, fetch: () => Promise<Msg[]>): Promise<void> {
    this.msgs = { ...this.msgs, [key]: [] };
    this.seen[key] = new Set();
    try {
      const list = await fetch();
      const s = new Set<string | number>();
      for (const m of list) if (m.id != null) s.add(m.id);
      this.seen[key] = s;
      this.msgs = { ...this.msgs, [key]: Array.isArray(list) ? list : [] };
    } catch (e) {
      this.noteMsg(e instanceof Error ? e.message : String(e));
    }
  }

  send(text: string): void {
    const cur = this.current;
    const t = text.trim();
    if (!cur || !t) return;
    const me = this.me;
    const optimistic: Msg = {
      id: "local-" + Math.random().toString(36).slice(2),
      content: t,
      created_at: new Date().toISOString(),
      sender_id: me?.id,
      sender: me ?? undefined,
    };
    this.msgs = { ...this.msgs, [cur.key]: [...(this.msgs[cur.key] || []), optimistic] };
    if (cur.kind === "room") this.api.sendRoom(Number(cur.id), t);
    else this.api.sendDm(Number(cur.id), t);
  }

  // ---------------- события WS ----------------
  private wire(): void {
    this.api.onWsError = (m) => {
      if (m) this.noteMsg(m);
    };
    this.api.onAuthFailed = (m) => this.logout();
    this.api.onWs = (ev) => this.onEvent(ev);
    this.api.onWsReconnected = () => void this.loadData();
    // бинарные кадры аудио/видео -> движок звонков
    this.api.onWsMedia = (kind, flags, from, payload) => {
      this.calls?.handleMedia(kind, flags, from, payload);
    };
    // голосовой канал переживает обрыв: сокет поднимется, движок переанонсирует
    this.api.onWsMediaReconnected = () => this.calls?.onTransportBack();
    // возврат во вкладку: WebView/браузер мог заморозить таймеры
    const wake = () => {
      if (document.visibilityState === "visible") this.api.wsOpen();
    };
    document.addEventListener("visibilitychange", wake);
    window.addEventListener("focus", wake);
    window.addEventListener("online", () => this.api.wsOpen());
    // сторож тишины
    this.watchTimer = window.setInterval(() => this.api.wsWatch(), 15000);
  }

  private onEvent(ev: WsEvent): void {
    if (ev.type === "ping") {
      this.api.send({ type: "pong" });
      return;
    }
    // сигналинг звонков и демонстрации экрана: всё остальное — движку
    switch (ev.type) {
      case "call":
      case "call_offer":
      case "call_answer":
      case "call_ice":
      case "call_hangup":
      case "call_audio":
      case "screen_start":
      case "screen_frame":
      case "screen_stop":
        this.calls?.handleEvent(ev);
        return;
    }
    if (ev.type === "status") {
      if (ev.user_id == null) return;
      const next = new Set(this.online);
      if (ev.online) next.add(ev.user_id);
      else next.delete(ev.user_id);
      this.online = next;
      return;
    }
    if (ev.type === "room_message" && ev.message) {
      const key = "room/" + String(ev.room_id);
      const mid = ev.message.id;
      const s = this.seen[key] || (this.seen[key] = new Set());
      if (mid != null) {
        if (s.has(mid)) return;
        s.add(mid);
      }
      const cur = this.current;
      if (cur && cur.key === key) {
        this.msgs = { ...this.msgs, [key]: [...(this.msgs[key] || []), ev.message] };
      }
      return;
    }
    if (ev.type === "direct_message" && ev.message) {
      const sid = ev.message.sender_id != null ? ev.message.sender_id : ev.from_id;
      const key = "dm/" + String(sid);
      const mid = ev.message.id;
      const s = this.seen[key] || (this.seen[key] = new Set());
      if (mid != null) {
        if (s.has(mid)) return;
        s.add(mid);
      }
      const cur = this.current;
      if (cur && cur.key === key) {
        this.msgs = { ...this.msgs, [key]: [...(this.msgs[key] || []), ev.message] };
      } else {
        void this.api.conversations().then((c) => (this.convs = c)).catch(() => undefined);
      }
    }
  }
}

export const store = new Store();
