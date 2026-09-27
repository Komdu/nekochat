import { useEffect, useRef, useState } from "react";
import { useStore } from "../store";
import { Sidebar } from "./Sidebar";
import { Avatar } from "./Avatar";
import { fmtTime } from "../format";
import type { Msg, User } from "../types";
import { SettingsDialog } from "./dialogs/SettingsDialog";
import { ProfileDialog } from "./dialogs/ProfileDialog";
import { NewDmDialog } from "./dialogs/NewDmDialog";
import { CreateRoomDialog } from "./dialogs/CreateRoomDialog";
import { AddMemberDialog } from "./dialogs/AddMemberDialog";

export function ChatPage() {
  const {
    me, current, msgs, usersMap, online, rooms, note,
    selectRoom, selectUser, send, logout, refreshData, startCall, startRoomCall,
  } = useStore();
  const [dlg, setDlg] = useState<string | null>(null);
  const [text, setText] = useState("");

  const key = current ? current.key : null;
  const list = key ? msgs[key] || [] : [];
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [key, list.length]);

  if (!current || !me) {
    return (
      <div className="app">
        <Sidebar />
        <main className="chat">
          <div className="empty-chat">Выбери комнату или собеседника слева</div>
        </main>
      </div>
    );
  }

  const headerBtns = (
    <>
      {(current.kind === "dm" || current.kind === "room") && (
        <button
          className="icon-btn"
          title={current.kind === "room" ? "Голосовой канал комнаты" : "Позвонить (сигналинг через сервер)"}
          onClick={() => {
            if (current.kind === "dm") startCall(Number(current.id));
            else startRoomCall(Number(current.id));
          }}
        >
          📞
        </button>
      )}
      <button className="icon-btn" title="Новые личные сообщения" onClick={() => setDlg("newdm")}>
        ✉
      </button>
      <button className="icon-btn" title="Создать комнату" onClick={() => setDlg("room")}>
        ➕
      </button>
      {current.kind === "room" && (
        <button className="icon-btn" title="Добавить участника" onClick={() => setDlg("member")}>
          👤
        </button>
      )}
      <button className="icon-btn" title="Обновить" onClick={() => refreshData(false)}>
        ⟳
      </button>
      <button className="icon-btn" title="Профиль" onClick={() => setDlg("profile")}>
        ☰
      </button>
      <button className="icon-btn" title="Настройки" onClick={() => setDlg("settings")}>
        ⚙
      </button>
      <button className="icon-btn" title="Выйти" onClick={() => logout()}>
        ⏻
      </button>
    </>
  );

  let sub = "";
  let statusOnline: boolean | undefined;
  if (current.kind === "room") {
    const r = rooms.find((x) => String(x.id) === current.id);
    const n = r ? r.member_count ?? (r.members ? r.members.length : 0) : 0;
    sub = n ? `${n} участников` : "";
  } else {
    sub = "личные сообщения";
    const u = usersMap[Number(current.id)];
    statusOnline = !!u && (online.has(u.id) || !!u.is_online);
  }

  return (
    <div className="app">
      <Sidebar />
      <main className="chat">
        <header className="chat-head">
          <div className="chat-titlebox">
            <Avatar
              user={current.kind === "dm" ? usersMap[Number(current.id)] : null}
              size={34}
              online={current.kind === "dm" ? statusOnline : undefined}
              className="chat-avatar"
            />
            <div className="chat-titles">
              <div className="chat-title">{current.label}</div>
              <div className="chat-sub">
                {statusOnline !== undefined
                  ? statusOnline ? "в сети" : "не в сети"
                  : sub || "\u00a0"}
              </div>
            </div>
          </div>
          <div className="chat-btns">{headerBtns}</div>
        </header>

        <div className="msgs" ref={scrollRef}>
          {list.length === 0 ? (
            <div className="empty-msgs">Пока пусто. Напиши первым!</div>
          ) : (
            list.map((m) => <Bubble key={String(m.id ?? Math.random())} msg={m} />)
          )}
        </div>

        {note && <div className="note-bar">{note}</div>}

        <div className="chat-input-row">
          <input
            className="chat-input"
            value={text}
            placeholder="Сообщение…"
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                if (text.trim()) {
                  send(text);
                  setText("");
                }
              }
            }}
          />
          <button
            className="btn-primary send-btn"
            disabled={!text.trim()}
            onClick={() => {
              send(text);
              setText("");
            }}
          >
            Отправить
          </button>
        </div>
      </main>

      {dlg === "settings" && <SettingsDialog onClose={() => setDlg(null)} />}
      {dlg === "profile" && <ProfileDialog onClose={() => setDlg(null)} />}
      {dlg === "newdm" && (
        <NewDmDialog onClose={() => setDlg(null)} onPick={(u) => { selectUser(u); setDlg(null); }} />
      )}
      {dlg === "room" && <CreateRoomDialog onClose={() => setDlg(null)} />}
      {dlg === "member" && current.kind === "room" && (
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
      <Avatar user={sender || msg.user} size={34} className="msg-avatar" />
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