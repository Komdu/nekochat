import { useState } from "react";
import { useStore } from "../../store";

export function CreateRoomDialog({ onClose }: { onClose: () => void }) {
  const { createRoom, noteMsg } = useStore();
  const [name, setName] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const create = async () => {
    const n = name.trim();
    if (!n) {
      setErr("Укажи название");
      return;
    }
    setBusy(true);
    setErr("");
    try {
      await createRoom(n);
      noteMsg(`Комната «${n}» создана`);
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
        <h2 className="dialog-title">Создать комнату</h2>
        <label className="field">
          <span>Название</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && create()}
            autoFocus
          />
        </label>
        {err && <div className="login-err">{err}</div>}
        <div className="dialog-btns">
          <button className="btn-primary" disabled={busy} onClick={create}>
            {busy ? "Создаём…" : "Создать"}
          </button>
        </div>
      </div>
    </div>
  );
}