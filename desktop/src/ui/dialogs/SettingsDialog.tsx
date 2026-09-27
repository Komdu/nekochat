import { useState } from "react";
import { useStore } from "../../store";
import { PRESETS } from "../../theme";

export function SettingsDialog({ onClose }: { onClose: () => void }) {
  const { theme, setTheme, fileTheme, reloadFileTheme } = useStore();
  const [t, setT] = useState({
    theme: theme.theme,
    mode: theme.mode,
    accent: theme.accent,
  });

  const apply = (patch: Partial<typeof t>) => {
    const next = { ...t, ...patch };
    setT(next);
    setTheme(next);
  };

  const fileMode = t.theme === "file";

  return (
    <div className="overlay" onClick={onClose}>
      <div className="dialog" onClick={(e) => e.stopPropagation()}>
        <h2 className="dialog-title">Настройки</h2>

        <div className="fgroup">
          <div className="fgroup-label">Тема</div>
          <div className="row">
            <label className="radio"><input type="radio" checked={t.theme === "material"} onChange={() => apply({ theme: "material" })} /> Material You</label>
            <label className="radio"><input type="radio" checked={t.theme === "win98"} onChange={() => apply({ theme: "win98" })} /> Win98</label>
            {fileTheme && (
              <label className="radio" title="%APPDATA%\nekochat\theme.json">
                <input
                  type="radio"
                  checked={t.theme === "file"}
                  onChange={() =>
                    apply({
                      theme: "file",
                      mode: fileTheme.mode ?? t.mode,
                      accent: fileTheme.accent ?? t.accent,
                    })
                  }
                />
                {fileTheme.name ? `Файл: ${fileTheme.name}` : "Из файла"}
              </label>
            )}
          </div>
        </div>

        <div className="fgroup">
          <div className="fgroup-label">Режим (Material You)</div>
          <div className="row">
            <label className={"radio" + (t.theme !== "material" ? " disabled" : "")}>
              <input type="radio" disabled={t.theme !== "material"} checked={t.theme === "material" && t.mode === "light"} onChange={() => apply({ mode: "light" })} /> Светлая
            </label>
            <label className={"radio" + (t.theme !== "material" ? " disabled" : "")}>
              <input type="radio" disabled={t.theme !== "material"} checked={t.theme === "material" && t.mode === "dark"} onChange={() => apply({ mode: "dark" })} /> Тёмная
            </label>
          </div>
        </div>

        <div className="fgroup">
          <div className="fgroup-label">Акцент</div>
          <div className="swatches">
            {Object.entries(PRESETS).map(([name, hex]) => (
              <button
                key={name}
                className={"swatch" + (t.accent === name ? " active" : "")}
                style={{ background: hex }}
                title={name}
                disabled={fileMode}
                onClick={() => apply({ accent: name })}
              />
            ))}
            <label
              className={"swatch swatch-custom" + (/^#?[0-9a-f]{6}$/i.test(t.accent) ? " active" : "")}
              title="Свой цвет"
            >
              <input
                type="color"
                disabled={fileMode}
                value={/^#?[0-9a-f]{6}$/i.test(t.accent) ? t.accent : "#6750a4"}
                onChange={(e) => apply({ accent: e.target.value })}
              />
            </label>
          </div>
          {fileMode && <div className="login-note">Акцент задаётся файлом theme.json</div>}
        </div>

        <div className="fgroup">
          <div className="fgroup-label">Транспорт</div>
          <div className="login-note">WebSocket (/ws) — единственный активный транспорт.</div>
        </div>

        <div className="dialog-btns">
          {fileTheme && (
            <button className="btn-secondary" onClick={() => reloadFileTheme()}>
              Перечитать файл
            </button>
          )}
          <button className="btn-primary" onClick={onClose}>Готово</button>
        </div>
        {fileTheme && <div className="login-note">%APPDATA%\nekochat\theme.json</div>}
      </div>
    </div>
  );
}