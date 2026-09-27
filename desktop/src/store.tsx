// Состояние приложения: порт логики ChatWindow из client_ui/chat.py
// (сессии, списки, сообщения, WS, оптимистичная отправка) на React.

import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
} from "react";
import type { ReactNode } from "react";
import { ApiClient } from "./api";
import { CallEngine, type CallState } from "./calls";
import type { Conversation, Current, Msg, Room, User, WsEvent } from "./types";
import { nowIso } from "./format";
import { applyTheme, defaultSettings, readFileTheme, loadFileTheme, type ThemeSettings, type FileTheme } from "./theme";

export const DEFAULT_BASE = "https://nekochat.komdu.is-cool.dev/";
const LS = {
  base: "nk.base",
  token: "nk.token",
  user: "nk.user",
  theme: "nk.theme",
  mode: "nk.mode",
  accent: "nk.accent",
  last: (base: string) => `nk.last.${base}`,
};

type Phase = "boot" | "login" | "ready";

interface Store {
  phase: Phase;
  me: User | null;
  api: ApiClient | null;
  base: string;
  rooms: Room[];
  convs: Conversation[];
  users: User[];
  usersMap: Record<number, User>;
  online: Set<number>;
  current: Current | null;
  msgs: Record<string, Msg[]>;
  theme: ThemeSettings;
  fileTheme: FileTheme | null;
  note: string;
  busy: boolean;
  call: CallState;
  startCall: (peerId: number) => void;
  startRoomCall: (roomId: number) => void;
  acceptCall: () => void;
  declineCall: () => void;
  hangupCall: () => void;
  toggleMuteCall: () => void;
  dismissCall: () => void;
  startScreenShare: () => void;
  stopScreenShare: () => void;
  setScreenCanvas: (peerId: number | null, el: HTMLCanvasElement | null) => void;
  login: (u: string, p: string, server?: string) => Promise<void>;
  register: (u: string, p: string, d: string, server?: string) => Promise<void>;
  logout: (reason?: string) => void;
  selectRoom: (r: Room) => void;
  selectUser: (u: User) => void;
  send: (text: string) => void;
  setTheme: (t: Partial<ThemeSettings>) => void;
  reloadFileTheme: () => Promise<void>;
  setBase: (b: string) => void;
  refreshData: (openLast?: boolean) => void;
  refreshConvs: () => void;
  createRoom: (name: string) => Promise<Room>;
  joinRoom: (id: number) => Promise<void>;
  addMember: (roomId: number, username: string) => Promise<void>;
  updateProfile: (p: { bio?: string; status?: string; profile_color?: string }) => Promise<void>;
  uploadAvatar: (f: File) => Promise<void>;
  clearMsgs: () => void;
  noteMsg: (m: string) => void;
}

const Ctx = createContext<Store | null>(null);

/** Поднимает бинарный медиа-сокет и прокидывает кадры в движок звонков.
 *  Аудио/видео идут мимо JSON-канала /ws — отдельным сокетом с приоритетными
 *  очередями на сервере (см. app/ws_media.py). Если сокет не поднялся, движок
 *  сам откатится на старый JSON-путь. */
function wireMedia(api: ApiClient, engine: () => CallEngine | null): void {
  api.onWsMedia = (kind, flags, from, payload) => {
    engine()?.handleMedia(kind, flags, from, payload);
  };
  api.onWsMediaLost = () => {
    // голосовой канал это переживает: сокет поднимется, CallEngine переанонсирует
    engine()?.onTransportBack?.();
  };
  api.onWsMediaReconnected = () => {
    engine()?.onTransportBack?.();
  };
  api.wsMediaOpen("media");
}

export function useStore(): Store {
  const s = useContext(Ctx);
  if (!s) throw new Error("useStore вне Provider");
  return s;
}

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
    /* noop */
  }
}

function lastJson(base: string): { kind: string; id: string } | null {
  try {
    const raw = localStorage.getItem(LS.last(base));
    return raw ? (JSON.parse(raw) as { kind: string; id: string }) : null;
  } catch {
    return null;
  }
}

export function StoreProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<User | null>(null);
  const [base, setBaseState] = useState<string>(() => localStorage.getItem(LS.base) || DEFAULT_BASE);
  const [phase, setPhase] = useState<Phase>("boot");
  const [rooms, setRooms] = useState<Room[]>([]);
  const [convs, setConvs] = useState<Conversation[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [usersMap, setUsersMap] = useState<Record<number, User>>({});
  const [online, setOnline] = useState<Set<number>>(new Set());
  const [current, setCurrent] = useState<Current | null>(null);
  const [msgs, setMsgs] = useState<Record<string, Msg[]>>({});
  const [theme, setThemeState] = useState<ThemeSettings>(() => {
    const t = defaultSettings();
    t.theme = localStorage.getItem(LS.theme) || t.theme;
    t.mode = localStorage.getItem(LS.mode) || t.mode;
    t.accent = localStorage.getItem(LS.accent) || t.accent;
    return t;
  });
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [fileTheme, setFileTheme] = useState<FileTheme | null>(null);
  const [call, setCall] = useState<CallState>({
    phase: "idle", peerId: null, roomId: null, inviterId: null, startedAt: null, muted: false, reason: "",
    screenOn: false, screenActive: false, screenError: "", participants: [],
  });
  const callRef = useRef<CallEngine | null>(null);

  const apiRef = useRef<ApiClient | null>(null);
  const meRef = useRef<User | null>(null);
  const currentRef = useRef<Current | null>(null);
  const msgsRef = useRef<Record<string, Msg[]>>({});
  const seenRef = useRef<Record<string, Set<string | number>>>({});
  const optRef = useRef<Record<string, Msg[]>>({});

  const applyAndSaveTheme = useCallback((t: Partial<ThemeSettings>) => {
    setThemeState((prev) => {
      const next = { ...prev, ...t };
      localStorage.setItem(LS.theme, next.theme);
      localStorage.setItem(LS.mode, next.mode);
      localStorage.setItem(LS.accent, next.accent);
      applyTheme(next.theme, next.mode, next.accent);
      return next;
    });
  }, []);

  // первичная тема до загрузки + чтение theme.json из файла
  useEffect(() => {
    let alive = true;
    (async () => {
      const ft = await readFileTheme();
      if (!alive) return;
      loadFileTheme(ft);
      setFileTheme(ft);
      applyTheme(theme.theme, theme.mode, theme.accent);
    })();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const reloadFileTheme = useCallback(async () => {
    const ft = await readFileTheme();
    loadFileTheme(ft);
    setFileTheme(ft);
    applyTheme(theme.theme, theme.mode, theme.accent);
  }, [theme.theme, theme.mode, theme.accent]);

  const noteMsg = useCallback((m: string) => {
    setNote(m);
    if (m) window.setTimeout(() => setNote(""), 6000);
  }, []);

  const setBase = useCallback((b: string) => {
    const bb = b.trim();
    if (!bb) return;
    setBaseState(bb);
    localStorage.setItem(LS.base, bb);
  }, []);

  const refreshConvs = useCallback(() => {
    const api = apiRef.current;
    if (!api) return;
    api
      .conversations()
      .then((cs) => {
        setConvs(cs);
        const csArr = Array.isArray(cs) ? cs : [];
        setUsersMap((prev) => {
          const next = { ...prev };
          for (const c of csArr) {
            const u = c && c.user;
            if (u && u.id != null) next[u.id] = { ...(prev[u.id] || {}), ...u };
          }
          return next;
        });
      })
      .catch(() => undefined);
  }, []);

  const appendMsg = useCallback((key: string, msg: Msg) => {
    setMsgs((prev) => ({ ...prev, [key]: [...(prev[key] || []), msg] }));
  }, []);

  const seedHistory = useCallback((key: string, list: Msg[]) => {
    const arr = Array.isArray(list) ? list : [];
    const seen = seenRef.current;
    const s = seen[key] || (seen[key] = new Set());
    const out: Msg[] = [];
    for (const m of arr) {
      const mid = m.id;
      if (mid != null) s.add(mid);
      out.push(m);
    }
    msgsRef.current = { ...msgsRef.current, [key]: out };
    setMsgs((prev) => ({ ...prev, [key]: out }));
  }, []);

  const openHistory = useCallback((key: string, fetcher: () => Promise<Msg[]>) => {
    seedHistory(key, []);
    fetcher()
      .then((list) => seedHistory(key, list))
      .catch((e) => noteMsg(e.message));
  }, [seedHistory, noteMsg]);

  const handleWs = useCallback((ev: WsEvent) => {
    const api = apiRef.current;
    if (!api) return;
    if (ev.type === "ping") {
      api.wsPong();
      return;
    }
    if (
      ev.type === "call" || ev.type === "call_offer" ||
      ev.type === "call_answer" || ev.type === "call_ice" ||
      ev.type === "call_hangup" || ev.type === "call_audio" ||
      ev.type === "screen_start" || ev.type === "screen_frame" ||
      ev.type === "screen_stop"
    ) {
      callRef.current?.handleEvent(ev);
      return;
    }
    if (ev.type === "status") {
      const uid = ev.user_id;
      if (uid == null) return;
      setOnline((prev) => {
        const next = new Set(prev);
        if (ev.online) next.add(uid);
        else next.delete(uid);
        return next;
      });
      setUsersMap((prev) =>
        prev[uid] ? { ...prev, [uid]: { ...prev[uid], is_online: !!ev.online } } : prev,
      );
      return;
    }
    if (ev.type === "room_message" && ev.message) {
      const key = "room/" + String(ev.room_id);
      const mid = ev.message.id;
      const seen = seenRef.current;
      const s = seen[key] || (seen[key] = new Set());
      if (mid != null) {
        if (s.has(mid)) return;
        s.add(mid);
      }
      // оптимистичная отправка: не дублируем свой же эхо
      const cur = currentRef.current;
      if (cur && cur.kind === "room" && cur.key === key) {
        const optList = optRef.current[key];
        if (optList && optList.length) {
          const content = String(ev.message.content || "");
          for (let i = 0; i < optList.length; i++) {
            if (String(optList[i].content || "") === content) {
              optList.splice(i, 1);
              return;
            }
          }
        }
        appendMsg(key, ev.message);
      }
      return;
    }
    if (ev.type === "direct_message" && ev.message) {
      const sid = ev.message.sender_id != null ? ev.message.sender_id : ev.from_id;
      const key = "dm/" + String(sid);
      const mid = ev.message.id;
      const seen = seenRef.current;
      const s = seen[key] || (seen[key] = new Set());
      if (mid != null) {
        if (s.has(mid)) return;
        s.add(mid);
      }
      const cur = currentRef.current;
      if (cur && cur.kind === "dm" && cur.key === key) {
        const optList = optRef.current[key];
        if (optList && optList.length) {
          const content = String(ev.message.content || "");
          for (let i = 0; i < optList.length; i++) {
            if (String(optList[i].content || "") === content) {
              optList.splice(i, 1);
              return;
            }
          }
        }
        appendMsg(key, ev.message);
      } else {
        refreshConvs();
      }
    }
  }, [appendMsg, refreshConvs]);

  const logout = useCallback((reason?: string) => {
    apiRef.current?.wsMediaClose();
    apiRef.current?.wsClose();
    apiRef.current = null;
    callRef.current?.destroy();
    callRef.current = null;
    meRef.current = null;
    seenRef.current = {};
    optRef.current = {};
    setMe(null);
    setRooms([]);
    setConvs([]);
    setUsers([]);
    setUsersMap({});
    setOnline(new Set());
    setCurrent(null);
    setMsgs({});
    msgsRef.current = {};
    localStorage.removeItem(LS.token);
    localStorage.removeItem(LS.user);
    setPhase("login");
    if (reason) noteMsg(reason);
  }, [noteMsg]);

  const loadData = useCallback(async (openLast: boolean, attempt = 1) => {
    const api = apiRef.current;
    if (!api) return;
    try {
      const [rs, us, cs] = await Promise.all([
        api.rooms(),
        api.users(),
        api.conversations(),
      ]);
      const roomsArr = Array.isArray(rs) ? rs : [];
      const usersArr = (Array.isArray(us) ? us : []).filter((u) => u.id !== api.meId);
      const convsArr = Array.isArray(cs) ? cs : [];
      setRooms(roomsArr);
      setUsers(usersArr);
      setConvs(convsArr);
      const map: Record<number, User> = {};
      for (const r of roomsArr) for (const m of r.members || []) if (m && m.id != null) map[m.id] = { ...(map[m.id] || {}), ...m };
      for (const u of usersArr) map[u.id] = { ...(map[u.id] || {}), ...u };
      for (const c of convsArr) if (c.user && c.user.id != null) map[c.user.id] = { ...(map[c.user.id] || {}), ...c.user };
      setUsersMap(map);
      if (openLast) {
        const last = lastJson(api.base);
        let target: { room?: Room; user?: User } = {};
        if (last && last.kind === "room") {
          const r = roomsArr.find((x) => String(x.id) === String(last.id));
          if (r) target = { room: r };
        }
        if (last && last.kind === "dm" && !target.room) {
          const u =
            usersArr.find((x) => x.id === Number(last.id)) ||
            convsArr.find((c) => c.user && c.user.id === Number(last.id))?.user;
          if (u) target = { user: u };
        }
        if (!target.room && !target.user && roomsArr.length) target = { room: roomsArr[0] };
        if (!target.room && !target.user && usersArr.length) target = { user: usersArr[0] };
        if (!target.room && !target.user) {
          const u = convsArr.find((c) => c.user && c.user.id !== api.meId)?.user;
          if (u) target = { user: u };
        }
        if (target.room) selectRoomRef.current(target.room);
        else if (target.user) selectUserRef.current(target.user);
      }
      api.wsOpen();
    } catch (e) {
      // сетевой сбой или 5xx (рестарт сервера/«моргание» туннеля) — пробуем ещё раз,
      // чтобы один запрос не оставлял пустой список чатов.
      const interrupt = e as { network?: boolean; server?: boolean };
      if (attempt < 3 && (interrupt.network || interrupt.server)) {
        await new Promise((r) => window.setTimeout(r, 800 * attempt));
        return loadData(openLast, attempt + 1);
      }
      noteMsg(e instanceof Error ? e.message : String(e));
      // даже без данных открываем WS: события будут приходить, список доедет при следующей загрузке
      api.wsOpen();
    }
  }, [noteMsg]);

  // создать движок звонков для текущего api (meId известен после логина/восстановления)
  // привязать стенд бинарного сокета к уже созданному движку (boot-путь)
  const attachEngineMedia = useCallback((api: ApiClient) => {
    const eng = callRef.current;
    if (eng) eng.mediaSink = (kind, flags, target, payload) => api.sendMedia(kind, flags, target, payload);
  }, []);

  const ensureCallEngine = useCallback((meId: number) => {
    const api = apiRef.current;
    if (!api) return;
    callRef.current?.destroy();
    callRef.current = null;
    const engine = new CallEngine(meId, (m) => api.sendCallSignal(m));
    engine.wsStateGetter = () => api.wsReady();
    // аудио/видео — в бинарный сокет; sendMedia сам вернёт false, если он не готов
    engine.mediaSink = (kind, flags, target, payload) => api.sendMedia(kind, flags, target, payload);
    engine.onState = (s) => setCall(s);
    callRef.current = engine;
  }, []);

  const login = useCallback(async (username: string, password: string, server?: string) => {
    const baseUrl = (server && server.trim()) || base;
    const api = new ApiClient(baseUrl);
    api.onWs = (ev) => handleWsRef.current(ev);
    api.onWsLost = () => handleWsLostRef.current();
    api.onWsReconnected = () => handleWsReconnectedRef.current();
    api.onWsError = (m) => {
      if (m) noteMsg(m);
    };
    api.onAuthFailed = (m) => logout(`Сессия истекла: ${m}`);
    wireMedia(api, () => callRef.current);
    apiRef.current = api;
    setBusy(true);
    try {
      const user = await api.login(username, password);
      meRef.current = user;
      localStorage.setItem(LS.token, api.token || "");
      saveJson(LS.user, user);
      localStorage.setItem(LS.base, baseUrl);
      setBaseState(baseUrl);
      setMe(user);
      setPhase("ready");
      ensureCallEngine(user.id);
      attachEngineMedia(api);
      api.wsMediaOpen("media");
      await loadData(true);
    } catch (e) {
      apiRef.current = null;
      throw e;
    } finally {
      setBusy(false);
    }
  }, [base, loadData, logout, noteMsg, ensureCallEngine]);

  const register = useCallback(async (username: string, password: string, display: string, server?: string) => {
    const baseUrl = (server && server.trim()) || base;
    const api = new ApiClient(baseUrl);
    api.onWs = (ev) => handleWsRef.current(ev);
    api.onWsLost = () => handleWsLostRef.current();
    api.onWsReconnected = () => handleWsReconnectedRef.current();
    api.onWsError = (m) => {
      if (m) noteMsg(m);
    };
    api.onAuthFailed = (m) => logout(`Сессия истекла: ${m}`);
    wireMedia(api, () => callRef.current);
    apiRef.current = api;
    setBusy(true);
    try {
      const user = await api.register(username, password, display);
      meRef.current = user;
      localStorage.setItem(LS.token, api.token || "");
      saveJson(LS.user, user);
      localStorage.setItem(LS.base, baseUrl);
      setBaseState(baseUrl);
      setMe(user);
      setPhase("ready");
      ensureCallEngine(user.id);
      attachEngineMedia(api);
      api.wsMediaOpen("media");
      await loadData(true);
    } catch (e) {
      apiRef.current = null;
      throw e;
    } finally {
      setBusy(false);
    }
  }, [base, loadData, logout, noteMsg, ensureCallEngine]);

  const selectRoom = useCallback((r: Room) => {
    const key = "room/" + String(r.id);
    const label = "# " + (r.name || "");
    const cur: Current = { kind: "room", id: String(r.id), key, label };
    currentRef.current = cur;
    setCurrent(cur);
    localStorage.setItem(LS.last(base), JSON.stringify({ kind: "room", id: String(r.id) }));
    openHistory(key, () => (apiRef.current ? apiRef.current.roomMessages(Number(r.id)) : Promise.resolve([])));
  }, [base, openHistory]);

  const selectUser = useCallback((u: User) => {
    const key = "dm/" + String(u.id);
    const uid = String(u.id);
    const label = "@ " + (u.display_name || u.username || uid);
    const cur: Current = { kind: "dm", id: uid, key, label };
    currentRef.current = cur;
    setCurrent(cur);
    setUsersMap((prev) => ({ ...prev, [u.id]: { ...(prev[u.id] || {}), ...u } }));
    localStorage.setItem(LS.last(base), JSON.stringify({ kind: "dm", id: Number(u.id) }));
    openHistory(key, () => (apiRef.current ? apiRef.current.dmMessages(Number(u.id)) : Promise.resolve([])));
  }, [base, openHistory]);

  const send = useCallback((text: string) => {
    const cur = currentRef.current;
    const api = apiRef.current;
    if (!cur || !api) return;
    const t = text.trim();
    if (!t) return;
    const data: Msg = {
      id: "local-" + Math.random().toString(36).slice(2),
      content: t,
      created_at: nowIso(),
      sender_id: meRef.current ? meRef.current.id : -1,
      sender: meRef.current || undefined,
    };
    const opt = optRef.current;
    const opts = opt[cur.key] || (opt[cur.key] = []);
    opts.push(data);
    msgsRef.current = { ...msgsRef.current, [cur.key]: [...(msgsRef.current[cur.key] || []), data] };
    setMsgs((prev) => ({ ...prev, [cur.key]: [...(prev[cur.key] || []), data] }));
    if (cur.kind === "room") {
      api.sendRoom(cur.id, t);
    } else {
      api.sendDm(Number(cur.id), t);
    }
  }, []);

  // реф-обёртка для WS-хендлера (чтобы не протухали замыкания)
  const handleWsRef = useRef(handleWs);
  useEffect(() => {
    handleWsRef.current = handleWs;
  }, [handleWs]);

  // WS оборвался (туннель рвёт соединения каждые ~2-4 минуты). Голосовой канал комнаты
  // это переживает: переподключение ~1с, аудио возобновляется, на onopen делаем ре-анонс.
  // Для 1-1 даём окно на переподключение (8с) и только потом снимаем звонок — иначе
  // звонок умирал от любого короткого разрыва туннеля. В фазах incoming/outgoing не
  // обрываем сразу: принятие/отбой доедут через очередь сигналов (api.ts).
  const handleWsLost = useCallback(() => {
    const eng = callRef.current;
    if (!eng) return;
    const st = eng.current;
    if (st.roomId != null) return; // голосовой канал живёт через реконнект
    if (st.phase === "active") {
      const peer = st.peerId;
      window.setTimeout(() => {
        const now = callRef.current;
        if (!now || now.current.phase !== "active" || now.current.peerId !== peer) return;
        if (apiRef.current && apiRef.current.wsReady() === 1) return; // уже переподключился
        now.hangup("Соединение прервано");
      }, 8000);
    }
  }, []);
  const handleWsLostRef = useRef(handleWsLost);
  useEffect(() => {
    handleWsLostRef.current = handleWsLost;
  }, [handleWsLost]);

  // WS переподключился: обновляем данные и в голосовом канале повторяем анонс присутствия,
  // чтобы остальные участники (и те, кто зашёл в комнату за время обрыва) снова нас видели.
  const handleWsReconnected = useCallback(() => {
    void loadData(false);
    callRef.current?.onTransportBack?.();
  }, [loadData]);
  const handleWsReconnectedRef = useRef(handleWsReconnected);
  useEffect(() => {
    handleWsReconnectedRef.current = handleWsReconnected;
  }, [handleWsReconnected]);

  const selectRoomRef = useRef(selectRoom);
  useEffect(() => {
    selectRoomRef.current = selectRoom;
  }, [selectRoom]);
  const selectUserRef = useRef(selectUser);
  useEffect(() => {
    selectUserRef.current = selectUser;
  }, [selectUser]);

  // boot: восстановление сессии из localStorage
  useEffect(() => {
    const token = localStorage.getItem(LS.token);
    const savedBase = localStorage.getItem(LS.base) || DEFAULT_BASE;
    const savedUser = loadJson<User | null>(LS.user, null);
    if (!token || !savedUser) {
      setPhase("login");
      return;
    }
    setBase(savedBase);
    const api = new ApiClient(savedBase);
    api.token = token;
    if (savedUser) {
      api.user = savedUser;
      api.meId = savedUser.id;
    }
    api.onWs = (ev) => handleWsRef.current(ev);
    api.onWsLost = () => handleWsLostRef.current();
    api.onWsReconnected = () => handleWsReconnectedRef.current();
    api.onWsError = (m) => {
      if (m) noteMsg(m);
    };
    api.onAuthFailed = (m) => logout(`Сессия истекла: ${m}`);
    wireMedia(api, () => callRef.current);
    apiRef.current = api;
    meRef.current = savedUser;
    setMe(savedUser);
    ensureCallEngine(savedUser.id);
    // сервер мог только что перезапускаться / туннель «моргнуть» — на сетевые сбои и 5xx
    // пробуем несколько раз, прежде чем уводить пользователя на экран входа
    const bootMe = (attempt: number): Promise<User> =>
      api.me().catch((e) => {
        const interrupt = e as { network?: boolean; server?: boolean };
        if (attempt < 3 && (interrupt.network || interrupt.server)) {
          return new Promise((r) => window.setTimeout(r, 700 * attempt)).then(() =>
            bootMe(attempt + 1)
          );
        }
        throw e;
      });
    bootMe(1)
      .then((u) => {
        meRef.current = u;
        localStorage.setItem(LS.token, api.token || "");
        saveJson(LS.user, u);
        setMe(u);
        setPhase("ready");
        attachEngineMedia(api);
        api.wsMediaOpen("media");
        return loadData(true);
      })
      .catch((e) => {
        // 401 уже обработан onAuthFailed → logout. Иначе просто на вход.
        if (apiRef.current === api) logout(String(e.message || "Сессия истекла"));
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // возврат в окно: если WS разорвали в фоне (idle-таймаут туннеля / свёрнутое окно —
  // WebView2 замораживает таймеры и heartbeat), переподключаемся сразу, не дожидаясь
  // протухшего таймера ретрая. wsOpen() сам не трогает уже открытое соединение.
  useEffect(() => {
    const onActive = () => {
      if (document.visibilityState === "visible") apiRef.current?.wsOpen();
    };
    const onOnline = () => apiRef.current?.wsOpen();
    document.addEventListener("visibilitychange", onActive);
    window.addEventListener("focus", onActive);
    window.addEventListener("online", onOnline);
    return () => {
      document.removeEventListener("visibilitychange", onActive);
      window.removeEventListener("focus", onActive);
      window.removeEventListener("online", onOnline);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const refreshData = useCallback((openLast?: boolean) => {
    loadData(!!openLast);
  }, [loadData]);

  const createRoom = useCallback(async (name: string): Promise<Room> => {
    const api = apiRef.current;
    if (!api) throw new Error("Не авторизован");
    const r = await api.createRoom(name);
    await loadData(false);
    selectRoomRef.current(r);
    return r;
  }, [loadData]);

  const joinRoom = useCallback(async (id: number) => {
    const api = apiRef.current;
    if (!api) throw new Error("Не авторизован");
    await api.joinRoom(id);
    await loadData(false);
  }, [loadData]);

  const addMember = useCallback(async (roomId: number, username: string) => {
    const api = apiRef.current;
    if (!api) throw new Error("Не авторизован");
    await api.addMember(roomId, username);
    await loadData(false);
  }, [loadData]);

  const updateProfile = useCallback(async (p: { bio?: string; status?: string; profile_color?: string }) => {
    const api = apiRef.current;
    if (!api) throw new Error("Не авторизован");
    await api.updateProfile(p);
    if (meRef.current) {
      const next = { ...meRef.current, ...p };
      meRef.current = next;
      setMe(next);
      saveJson(LS.user, next);
    }
  }, []);

  const uploadAvatar = useCallback(async (f: File) => {
    const api = apiRef.current;
    if (!api) throw new Error("Не авторизован");
    await api.uploadAvatar(f);
    const u = await api.me();
    meRef.current = u;
    setMe(u);
    saveJson(LS.user, u);
  }, []);

  const clearMsgs = useCallback(() => {
    seenRef.current = {};
    optRef.current = {};
    msgsRef.current = {};
    setMsgs({});
  }, []);

  const startCall = useCallback((peerId: number) => {
    void callRef.current?.start(peerId);
  }, []);
  const startRoomCall = useCallback((roomId: number) => {
    void callRef.current?.startRoomCall(roomId);
  }, []);
  const acceptCall = useCallback(() => {
    void callRef.current?.accept();
  }, []);
  const declineCall = useCallback(() => {
    callRef.current?.decline();
  }, []);
  const hangupCall = useCallback(() => {
    callRef.current?.hangup();
  }, []);
  const toggleMuteCall = useCallback(() => {
    callRef.current?.toggleMute();
  }, []);
  const dismissCall = useCallback(() => {
    callRef.current?.dismiss();
  }, []);
  const startScreenShare = useCallback(() => {
    void callRef.current?.startScreenShare();
  }, []);
  const stopScreenShare = useCallback(() => {
    callRef.current?.stopScreenShare();
  }, []);
  const setScreenCanvas = useCallback((peerId: number | null, el: HTMLCanvasElement | null) => {
    callRef.current?.setScreenCanvas(peerId, el);
  }, []);

  const value = useMemo<Store>(
    () => ({
      phase, me, api: apiRef.current, base, rooms, convs, users, usersMap, online,
      current, msgs, theme, fileTheme, note, busy,
      call, startCall, startRoomCall, acceptCall, declineCall, hangupCall, toggleMuteCall, dismissCall,
      startScreenShare, stopScreenShare, setScreenCanvas,
      login, register, logout, selectRoom, selectUser, send, setTheme: applyAndSaveTheme,
      reloadFileTheme,
      setBase,
      refreshData, refreshConvs, createRoom, joinRoom, addMember, updateProfile,
      uploadAvatar, clearMsgs, noteMsg,
    }),
    [phase, me, base, rooms, convs, users, usersMap, online, current, msgs, theme,
     fileTheme, note, busy, call, startCall, startRoomCall, acceptCall, declineCall, hangupCall,
     toggleMuteCall, dismissCall, startScreenShare, stopScreenShare, setScreenCanvas,
     login, register, logout, selectRoom, selectUser, send,
     applyAndSaveTheme, reloadFileTheme,
     setBase, refreshData, refreshConvs, createRoom, joinRoom, addMember, updateProfile,
     uploadAvatar, clearMsgs, noteMsg],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
