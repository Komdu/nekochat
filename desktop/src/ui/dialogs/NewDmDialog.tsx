import { useMemo, useState } from "react";
import { useStore } from "../../store";
import { Avatar } from "../Avatar";
import type { User } from "../../types";

export function NewDmDialog({ onClose, onPick }: { onClose: () => void; onPick: (u: User) => void }) {
  const { me, users, convs, usersMap, online } = useStore();
  const [q, setQ] = useState("");

  const list = useMemo(() => {
    const meId = me ? me.id : -1;
    const withDm = new Set(convs.map((c) => c.user?.id).filter((x): x is number => x != null));
    const all = users.filter((u) => u.id !== meId);
    const merged = all.map((u) => usersMap[u.id] || u);
    const qq = q.trim().toLowerCase();
    return merged.filter((u) => (u.display_name || u.username || "").toLowerCase().includes(qq));
  }, [users, usersMap, convs, me, q]);

  return (
    <div className="overlay" onClick={onClose}>
      <div className="dialog" onClick={(e) => e.stopPropagation()}>
        <h2 className="dialog-title">Новые личные сообщения</h2>
        <input
          className="chat-input"
          placeholder="Поиск…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          autoFocus
        />
        <div className="picklist">
          {list.length === 0 && <div className="empty-msgs">Никого не найдено</div>}
          {list.map((u) => (
            <button key={u.id} className="list-item" onClick={() => onPick(u)}>
              <Avatar user={u} size={32} online={online.has(u.id) || !!u.is_online} />
              <span className={"item-name" + (online.has(u.id) || !!u.is_online ? " online" : " off")}>
                {u.display_name || u.username || u.id}
              </span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}