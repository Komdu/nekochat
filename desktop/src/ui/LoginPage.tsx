import { useState } from "react";
import { useStore, DEFAULT_BASE } from "../store";

export function LoginPage() {
  const { login, register, busy, note } = useStore();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [server, setServer] = useState(() => localStorage.getItem("nk.base") || DEFAULT_BASE);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [display, setDisplay] = useState("");
  const [err, setErr] = useState("");

  const submit = async () => {
    setErr("");
    const u = username.trim();
    const p = password;
    const d = display.trim();
    if (!u || !p) {
      setErr("Введи логин и пароль");
      return;
    }
    if (mode === "register" && !d) {
      setErr("Укажи имя для отображения");
      return;
    }
    if (server.trim() !== localStorage.getItem("nk.base")) {
      localStorage.setItem("nk.base", server.trim());
    }
    try {
      window.location.hash = "";
      if (mode === "login") await login(u, p, server.trim());
      else await register(u, p, d, server.trim());
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="login-wrap">
      <div className="login-card">
        <div className="login-logo">#</div>
        <h1 className="login-title">Nekochat</h1>
        <div className="login-tabs">
          <button className={"tab" + (mode === "login" ? " active" : "")} onClick={() => setMode("login")}>
            Вход
          </button>
          <button className={"tab" + (mode === "register" ? " active" : "")} onClick={() => setMode("register")}>
            Регистрация
          </button>
        </div>

        <label className="field">
          <span>Сервер</span>
          <input value={server} onChange={(e) => setServer(e.target.value)} placeholder="https://…" />
        </label>
        <label className="field">
          <span>Логин</span>
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus spellCheck={false} />
        </label>
        {mode === "register" && (
          <label className="field">
            <span>Имя для отображения</span>
            <input value={display} onChange={(e) => setDisplay(e.target.value)} spellCheck={false} />
          </label>
        )}
        <label className="field">
          <span>Пароль</span>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()} />
        </label>

        {err && <div className="login-err">{err}</div>}
        {note && <div className="login-note">{note}</div>}

        <button className="btn-primary login-submit" disabled={busy} onClick={submit}>
          {busy ? "Подожди…" : mode === "login" ? "Войти" : "Создать аккаунт"}
        </button>
      </div>
    </div>
  );
}