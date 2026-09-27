import { useRef, useState } from "react";
import { useStore } from "../../store";
import { Avatar } from "../Avatar";
import { avatarColors } from "../../format";

export function ProfileDialog({ onClose }: { onClose: () => void }) {
  const { me, updateProfile, uploadAvatar, noteMsg } = useStore();
  const me2 = me || ({} as any);
  const [status, setStatus] = useState(me2.status || "");
  const [bio, setBio] = useState(me2.bio || "");
  const [color, setColor] = useState(me2.profile_color || "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const save = async () => {
    setBusy(true);
    setErr("");
    try {
      await updateProfile({ status, bio, profile_color: color || null as any });
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const onFile = async (f: File | undefined) => {
    if (!f) return;
    setBusy(true);
    setErr("");
    try {
      await uploadAvatar(f);
      noteMsg("Аватар обновлён");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  return (
    <div className="overlay" onClick={onClose}>
      <div className="dialog" onClick={(e) => e.stopPropagation()}>
        <h2 className="dialog-title">Профиль</h2>

        <div className="prof-head">
          <Avatar user={me2} size={84} className="prof-av" />
          <div className="prof-names">
            <div className="prof-name">{me2.display_name || me2.username || "?"}</div>
            <div className="prof-user">@{me2.username || ""}</div>
            <button className="btn-secondary" disabled={busy} onClick={() => fileRef.current?.click()}>
              Сменить аватар
            </button>
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              hidden
              onChange={(e) => onFile(e.target.files?.[0])}
            />
          </div>
        </div>

        <label className="field">
          <span>Статус</span>
          <input value={status} onChange={(e) => setStatus(e.target.value)} placeholder="Статус…" />
        </label>
        <label className="field">
          <span>О себе</span>
          <textarea value={bio} onChange={(e) => setBio(e.target.value)} rows={2} placeholder="Био…" />
        </label>

        <div className="fgroup">
          <div className="fgroup-label">Цвет профиля</div>
          <div className="swatches">
            {avatarColors().map((hex) => (
              <button
                key={hex}
                className={"swatch" + (color === hex ? " active" : "")}
                style={{ background: hex }}
                onClick={() => setColor(hex)}
              />
            ))}
          </div>
        </div>

        {err && <div className="login-err">{err}</div>}

        <div className="dialog-btns">
          <button className="btn-primary" disabled={busy} onClick={save}>Сохранить</button>
        </div>
      </div>
    </div>
  );
}