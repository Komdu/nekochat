// Тёмная тема клиента: палитра задана в CSS-переменных, здесь только
// применение data-theme/data-mode. Значения — те же, что в styles.css
// десктопа и в app/static/web/index.html, чтобы клиенты выглядели одинаково.

export type ThemeStyle = "oled" | "material" | "win98";
export type ThemeMode = "light" | "dark";

const LS_THEME = "nk_theme";

function normalize(v: string | null): { style: ThemeStyle; mode: ThemeMode } {
  let s = v || "oled";
  if (/^standard-/.test(s)) s = s.replace("standard-", "material-");
  if (s === "material") s = "material-dark";
  if (s === "win98") s = "win98-dark";
  const m = /^(win98|material|oled)-(light|dark)$/.exec(s);
  if (!m) return { style: "oled", mode: "dark" };
  return { style: m[1] as ThemeStyle, mode: m[2] as ThemeMode };
}

export function theme(): { style: ThemeStyle; mode: ThemeMode } {
  try {
    return normalize(localStorage.getItem(LS_THEME));
  } catch {
    return { style: "oled", mode: "dark" };
  }
}

export function applyTheme(style: ThemeStyle, mode: ThemeMode): void {
  const root = document.documentElement;
  root.dataset.theme = style;
  root.dataset.mode = mode;
  try {
    localStorage.setItem(LS_THEME, `${style}-${mode}`);
  } catch {
    /* noop */
  }
}
