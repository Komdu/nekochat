import { useEffect, useRef, useState } from "react";
import { useStore } from "../store";
import { Avatar } from "./Avatar";
import { Icon } from "./Icon";

function fmtDur(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

export function CallOverlay() {
  const {
    call, usersMap, rooms,
    acceptCall, declineCall, hangupCall, toggleMuteCall, dismissCall, selectUser,
    startScreenShare, stopScreenShare, setScreenCanvas,
  } = useStore();
  const [now, setNow] = useState(() => Date.now());
  const [screenFull, setScreenFull] = useState(false);
  // холсты входящих демонстраций: peerId → canvas (и 1-1, и канал)
  const canvasRefs = useRef<Record<number, HTMLCanvasElement | null>>({});

  useEffect(() => {
    if (call.phase !== "active") return;
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, [call.phase, call.startedAt]);

  // регистрируем холсты: 1-1 — один экран собеседника, канал — по холсту на показывающего
  useEffect(() => {
    if (call.phase !== "active") return;
    if (call.roomId == null) {
      if (call.peerId != null) {
        setScreenCanvas(call.peerId, call.screenActive ? (canvasRefs.current[call.peerId] ?? null) : null);
      }
      return;
    }
    for (const p of call.participants) {
      setScreenCanvas(p.id, p.screen ? (canvasRefs.current[p.id] ?? null) : null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [call.phase, call.roomId, call.screenActive, call.participants, setScreenCanvas]);

  if (call.phase === "idle") return null;

  const isChannel = call.roomId != null;
  const muted = call.muted;

  let name = "…";
  let avatarUser = undefined as { id?: number; avatar?: string | null; profile_color?: string | null; display_name?: string | null; username?: string } | undefined;
  if (isChannel) {
    const r = rooms.find((x) => String(x.id) === String(call.roomId));
    name = r ? r.name : "Голосовой канал";
    if (call.phase === "incoming" && call.inviterId != null) avatarUser = usersMap[call.inviterId];
  } else if (call.peerId != null) {
    avatarUser = usersMap[call.peerId];
    name = avatarUser
      ? (avatarUser.display_name || avatarUser.username || `@${call.peerId}`)
      : `@${call.peerId}`;
  }

  // движок в participants хранит только чужих (себя он не добавляет)
  const channelMembers = isChannel ? call.participants : [];

  return (
    <div className="call-overlay">
      <div className={`call-card phase-${call.phase}`}>
        <Avatar user={avatarUser as any} size={64} className="call-avatar" />
        <div className="call-name">{name}</div>

        {isChannel && call.phase === "incoming" && (
          <div className="call-info">
            {call.inviterId != null
              ? (usersMap[call.inviterId]?.display_name || usersMap[call.inviterId]?.username || `@${call.inviterId}`)
              : "Кто-то"} приглашает в голосовой канал
          </div>
        )}
        {!isChannel && call.phase === "incoming" && <div className="call-info">Входящий звонок…</div>}
        {call.phase === "outgoing" && <div className="call-info">Вызов…</div>}
        {call.phase === "connecting" && (
          <div className="call-info">{isChannel ? "Вход в голосовой канал…" : "Соединение…"}</div>
        )}
        {call.phase === "active" && (
          <div className="call-info call-timer">
            {call.startedAt ? fmtDur(now - call.startedAt) : "00:00"}
            {isChannel && channelMembers.length > 0 && (
              <span className="call-muted-tag">в канале: {channelMembers.length + 1}</span>
            )}
            {muted && <span className="call-muted-tag">микрофон выкл</span>}
          </div>
        )}
        {call.phase === "ended" && <div className="call-info">{call.reason}</div>}

        {/* участники голосового канала (кроме меня) */}
        {isChannel && (call.phase === "active" || call.phase === "connecting") && (
          <div className="call-members">
            {channelMembers.map((p) => {
              const u = usersMap[p.id];
              const pname = u ? (u.display_name || u.username || `@${p.id}`) : `@${p.id}`;
              return (
                <div key={p.id} className="call-member">
                  <Avatar user={u} size={32} className="call-avatar" />
                  <div className="call-member-name">{pname}</div>
                  {p.screen && <div className="call-member-screen-tag"><Icon name="monitor" size={16} /></div>}
                  <div className="call-member-dot" />
                </div>
              );
            })}
            {channelMembers.length === 0 && (
              <div className="call-info">Пока никого — подожди, скоро подтянутся</div>
            )}
          </div>
        )}

        <div className="call-actions">
          {call.phase === "incoming" && (
            <>
              <button className="call-btn call-decline" onClick={declineCall}>
                {isChannel ? "Позже" : "Отклонить"}
              </button>
              <button
                className="call-btn call-accept"
                onClick={() => {
                  acceptCall();
                  if (!isChannel && call.peerId != null) selectUser({ ...(usersMap[call.peerId] || {}), id: call.peerId } as any);
                }}
              >
                {isChannel ? "Войти" : "Принять"}
              </button>
            </>
          )}
          {call.phase === "outgoing" && (
            <button className="call-btn call-decline" onClick={() => hangupCall()}>
              Отменить
            </button>
          )}
          {(call.phase === "connecting" || call.phase === "active") && (
            <>
              <button
                className={"call-btn call-mute" + (muted ? " call-mute-on" : "")}
                onClick={toggleMuteCall}
                title="Микрофон"
              >
                {muted ? <Icon name="micOff" size={17} /> : <Icon name="mic" size={17} />}
              </button>
              {call.phase === "active" && (
                <button
                  className={"call-btn call-screen" + (call.screenOn ? " call-screen-on" : "")}
                  onClick={() => {
                    if (call.screenOn) stopScreenShare();
                    else startScreenShare();
                  }}
                  title={call.screenOn ? "Остановить демонстрацию экрана" : "Демонстрация экрана"}
                >
                  {call.screenOn ? <><Icon name="stop" size={15} /> <Icon name="monitor" size={15} /></> : <Icon name="monitor" size={15} />}
                </button>
              )}
              <button className="call-btn call-decline" onClick={() => hangupCall()}>
                {isChannel ? "Выйти" : "Завершить"}
              </button>
            </>
          )}
          {call.phase === "ended" && (
            <button className="call-btn call-neutral" onClick={dismissCall}>
              Ок
            </button>
          )}
        </div>
        {call.screenError && call.phase === "active" && (
          <div className="call-info call-screen-error">{call.screenError}</div>
        )}
      </div>

      {/* демонстрации экрана: 1-1 — одна, канал — панель на каждого показывающего */}
      {isChannel ? (
        call.participants.filter((p) => p.screen).map((p) => {
          const u = usersMap[p.id];
          const pname = u ? (u.display_name || u.username || `@${p.id}`) : `@${p.id}`;
          return (
            <div key={p.id} className="call-screen-panel">
              <div className="call-screen-head">
                <span className="call-screen-title"><Icon name="monitor" size={15} /> {pname}</span>
              </div>
              <canvas
                ref={(el) => {
                  canvasRefs.current[p.id] = el;
                }}
                className="call-screen-canvas"
              />
            </div>
          );
        })
      ) : (
        call.screenActive &&
        call.phase === "active" &&
        call.peerId != null && (
          <div className={"call-screen-panel" + (screenFull ? " full" : "")}>
            <div className="call-screen-head">
              <span className="call-screen-title"><Icon name="monitor" size={15} /> Демонстрация экрана</span>
              <button className="call-btn call-neutral" onClick={() => setScreenFull(!screenFull)}>
                {screenFull ? "Свернуть" : "На весь экран"}
              </button>
            </div>
            <canvas
              ref={(el) => {
                canvasRefs.current[call.peerId!] = el;
              }}
              className="call-screen-canvas"
            />
          </div>
        )
      )}
    </div>
  );
}