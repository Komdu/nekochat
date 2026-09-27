import { useMemo } from "react";
import { useStore } from "../store";
import { Avatar } from "./Avatar";
import { Tile } from "./Tile";

export function Sidebar() {
  const { me, rooms, convs, users, usersMap, online, current, selectRoom, selectUser, logout, refreshData, base } =
    useStore();
  let host = base;
  try {
    host = new URL(base).host;
  } catch {
    /* noop */
  }

  const { dmUsers, people } = useMemo(() => {
    const meId = me ? me.id : -1;
    const seen = new Set<number>();
    const dm: any[] = [];
    for (const c of convs) {
      const u = c && c.user;
      if (u && u.id !== meId) {
        seen.add(u.id);
        dm.push(u);
      }
    }
    const rest = users.filter((u) => u.id !== meId && !seen.has(u.id));
    return { dmUsers: dm, people: rest };
  }, [convs, users, me]);

  const isOnline = (u: { id: number } | null | undefined): boolean =>
    !!u && (online.has(u.id) || !!usersMap[u.id]?.is_online);

  const roomActive = (id: number) => current && current.kind === "room" && current.id === String(id);
  const dmActive = (id: number) => current && current.kind === "dm" && current.id === String(id);

  return (
    <aside className="sidebar">
      <div className="side-head">
        <span className="side-logo">#</span>
        <div className="side-server">
          <div className="server-name">Nekochat</div>
          <div className="server-sub">комнаты и личные сообщения</div>
        </div>
        <button className="icon-btn side-refresh" title="Обновить" onClick={() => refreshData(false)}>
          ⟳
        </button>
      </div>

      {rooms.length > 0 && (
        <>
          <div className="sec-label">Комнаты</div>
          <div className="list">
            {rooms.map((r) => (
              <button
                key={r.id}
                className={"list-item" + (roomActive(r.id) ? " active" : "")}
                onClick={() => selectRoom(r)}
              >
                <Tile name={r.name || ""} size={30} />
                <span className="item-name">{r.name || ("#" + r.id)}</span>
              </button>
            ))}
          </div>
        </>
      )}

      {dmUsers.length > 0 && (
        <>
          <div className="sec-label">Личные сообщения</div>
          <div className="list">
            {dmUsers.map((u) => (
              <button
                key={u.id}
                className={"list-item" + (dmActive(u.id) ? " active" : "")}
                onClick={() => selectUser(u)}
              >
                <Avatar user={u} size={32} online={isOnline(u)} />
                <span className={"item-name" + (isOnline(u) ? " online" : " off")}>
                  {u.display_name || u.username || u.id}
                </span>
              </button>
            ))}
          </div>
        </>
      )}

      {people.length > 0 && (
        <>
          <div className="sec-label">Люди</div>
          <div className="list">
            {people.map((u) => (
              <button
                key={u.id}
                className={"list-item" + (dmActive(u.id) ? " active" : "")}
                onClick={() => selectUser(u)}
              >
                <Avatar user={u} size={32} online={isOnline(u)} />
                <span className={"item-name" + (isOnline(u) ? " online" : " off")}>
                  {u.display_name || u.username || u.id}
                </span>
              </button>
            ))}
          </div>
        </>
      )}

      <div className="side-foot">
        <button className="icon-btn" title="Выйти" onClick={() => logout()}>
          ⏻
        </button>
        <span className="server-url">{host}</span>
      </div>
    </aside>
  );
}