import { useEffect, useRef, useState } from "react";
import { useStore } from "../store";
import { Sidebar } from "./Sidebar";
import { Avatar } from "./Avatar";
import { PTile } from "./PTile";
import { fmtTime } from "../format";
import type { Msg, User } from "../types";
import { SettingsDialog } from "./dialogs/SettingsDialog";
import { ProfileDialog } from "./dialogs/ProfileDialog";
import { NewDmDialog } from "./dialogs/NewDmDialog";
import { CreateRoomDialog } from "./dialogs/CreateRoomDialog";
import { AddMemberDialog } from "./dialogs/AddMemberDialog";

/**
 * Экран чата по макету: шапка во всю ширину, контурные пузыри с хвостиком,
 * frameless-поле ввода и нижняя панель (участники | комнаты | меню/профиль).
 * Список комнат и людей уехал в выезжающую панель (☰ справа внизу).
 */
export function ChatPage() {
  const {
    me, current, msgs, usersMap, online, rooms, note,
    selectRoom, selectUser, send, refreshData, startCall, startRoomCall,
  } = useStore();
  const [dlg, setDlg] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [drawer, setDrawer] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);

  const key = current ? current.key : null;
  const list = key ? msgs[key] || [] : [];

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [key, list.length]);

  // поле ввода растёт под текст (до ~5 строк), как большая область на макете
  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 150) + "px";
  }, [text]);

  useEffect(() => {
    if (!drawer) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDrawer(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawer]);

  const isOnline = (u: Partial<User> | null | undefined): boolean =>
    !!u && u.id != null && (online.has(u.id) || !!usersMap[u.id]?.is_online);

  const room =
    current && current.kind === "room"
      ? rooms.find((x) => String(x.id) === current.id) || null
      : null;
  const peer = current && current.kind === "dm" ? usersMap[Number(current.id)] || null : null;

  const title = current
    ? room
      ? room.name || current.label.replace(/^#\s*/, "")
      : current.label.replace(/^@\s*/, "")
    : "";

  const people: User[] = room ? room.members || [] : peer ? [peer] : [];
  const memberCount = room ? room.member_count ?? (room.members ? room.members.length : 0) : 0;
  const sub = room
    ? `${memberCount} участников`
    : peer
      ? isOnline(peer) ? "в сети" : "не в сети"
      : "";

  const submit = () => {
    if (!text.trim()) return;
    send(text);
    setText("");
  };

  const appbar = (
    <nav className="appbar">
      <div className="appbar-people">
        {people.map((u) => (
          <PTile
            key={u.id}
            user={u}
            size={30}
            online={isOnline(u)}
            title={u.id === me?.id ? u.display_name || u.username : `Написать: ${u.display_name || u.username}`}
            onClick={u.id === me?.id ? undefined : () => selectUser(u)}
          />
        ))}
        <button className="ptile-btn ptile-add" title="Добавить участника" onClick={() => setDlg("member")}>
          +
        </button>
      </div>

      <div className="appbar-sep" />

      <div className="appbar-rooms">
        {rooms.map((r) => (
          <button
            key={r.id}
            className={"room-chip" + (current && current.kind === "room" && current.id === String(r.id) ? " active" : "")}
            title={r.name}
            onClick={() => selectRoom(r)}
          >
            <span className="hash">#</span>
            <span className="rname">{r.name}</span>
          </button>
        ))}
        <button className="room-chip add" title="Создать комнату" onClick={() => setDlg("room")}>
          +
        </button>
      </div>

      <div className="appbar-right">
        <button className="icon-btn" title="Каналы и люди" onClick={() => setDrawer((v) => !v)}>
          ☰
        </button>
        <span className="appbar-me">{me?.display_name || me?.username || ""}</span>
        <span className={"appbar-dot" + (me ? " on" : "")} title="в сети" />
      </div>
    </nav>
  );

  return (
    <div className="app">
      <header className="chat-head">
        <div className="chat-titlebox">
          <span className="chan-chip">{room ? "#" : "@"}</span>
          <div className="chat-titles">
            <div className="chat-title">{title || "Nekochat"}</div>
          </div>
        </div>
        <div className="chat-btns">
          {current && (current.kind === "dm" || current.kind === "room") && (
            <button
              className="icon-btn"
              title={current.kind === "room" ? "Голосовой канал комнаты" : "Позвонить"}
              onClick={() => {
                if (current.kind === "dm") startCall(Number(current.id));
                else startRoomCall(Number(current.id));
              }}
            >
              📞
            </button>
          )}
          {sub && <span className="chat-sub">{sub}</span>}
        </div>
      </header>

      <div className="msgs" ref={scrollRef}>
        {list.length === 0 ? (
          <div className="empty-msgs">
            {current ? "Пока пусто. Напиши первым!" : "Выбери комнату или собеседника"}
          </div>
        ) : (
          list.map((m) => <Bubble key={String(m.id ?? Math.random())} msg={m} />)
        )}
      </div>

      {note && <div className="note-bar">{note}</div>}

      <div className="composer">
        <textarea
          ref={taRef}
          className="composer-input"
          rows={1}
          value={text}
          placeholder="Сообщение…"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
      </div>

      {appbar}

      {drawer && (
        <>
          <div className="drawer-backdrop" onClick={() => setDrawer(false)} />
          <aside className="drawer">
            <div className="drawer-actions">
              <button className="icon-btn" title="Новые личные сообщения" onClick={() => setDlg("newdm")}>✉</button>
              <button className="icon-btn" title="Создать комнату" onClick={() => setDlg("room")}>➕</button>
              {current && current.kind === "room" && (
                <button className="icon-btn" title="Добавить участника" onClick={() => setDlg("member")}>👤</button>
              )}
              <button className="icon-btn" title="Обновить" onClick={() => refreshData(false)}>⟳</button>
              <button className="icon-btn" title="Профиль" onClick={() => setDlg("profile")}>☺</button>
              <button className="icon-btn" title="Настройки" onClick={() => setDlg("settings")}>⚙</button>
            </div>
            <Sidebar />
          </aside>
        </>
      )}

      {dlg === "settings" && <SettingsDialog onClose={() => setDlg(null)} />}
      {dlg === "profile" && <ProfileDialog onClose={() => setDlg(null)} />}
      {dlg === "newdm" && (
        <NewDmDialog onClose={() => setDlg(null)} onPick={(u) => { selectUser(u); setDrawer(false); }} />
      )}
      {dlg === "room" && <CreateRoomDialog onClose={() => setDlg(null)} />}
      {dlg === "member" && current && current.kind === "room" && (
        <AddMemberDialog roomId={Number(current.id)} onClose={() => setDlg(null)} />
      )}
    </div>
  );
}

function Bubble({ msg }: { msg: Msg }) {
  const { me, usersMap } = useStore();
  const uid = msg.sender_id != null ? msg.sender_id : msg.user_id;
  const mine = uid === me?.id;
  let sender: Partial<User> | undefined;
  if (msg.sender && typeof msg.sender === "object") sender = msg.sender;
  else if (uid != null) sender = usersMap[uid] || { id: uid, display_name: "@" + uid, username: "" };
  const name = (sender && (sender.display_name || sender.username)) || msg.user?.display_name || "?";
  const time = fmtTime(msg.created_at);

  return (
    <div className={"msg " + (mine ? "mine" : "theirs")}>
      <Avatar user={sender || msg.user} size={30} className="msg-avatar" />
      <div className="msg-body">
        <div className="msg-head">
          <span className="msg-name" style={sender && (sender as any).profile_color ? { color: (sender as any).profile_color } : undefined}>
            {name}
          </span>
          <span className="msg-time">{time}</span>
        </div>
        <div className="msg-text">{msg.content}</div>
      </div>
    </div>
  );
}
