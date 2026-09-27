import { useState } from "react";
import { useStore } from "../../store";

export function AddMemberDialog({ roomId, onClose }: { roomId: number; onClose: () => void }) {
  const { addMember, noteMsg } = useStore();
  const [username, setUsername] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const add = async () => {
    const u = username.trim();
    if (!u) {
      setErr("Укажи логин пользователя");
      return;
    }
    setBusy(true);
    setErr("");
    try {
      await addMember(roomId, u);
      noteMsg(`${u} добавлен(а) в комнату`);
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="overlay" onClick={onClose}>
      <div className="dialog" onClick={(e) => e.stopPropagation()}>
        <h2 className="dialog-title">Добавить участника</h2>
        <label className="field">
          <span>Логин</span>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && add()}
            autoFocus
          />
        </label>
        {err && <div className="login-err">{err}</div>}
        <div className="dialog-btns">
          <button className="btn-primary" disabled={busy} onClick={add}>
            {busy ? "Добавляем…" : "Добавить"}
          </button>
        </div>
      </div>
    </div>
  );
}