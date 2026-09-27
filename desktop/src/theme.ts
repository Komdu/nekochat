// Порт client_ui/theme.py: токены Material You (со стоковой базой, подъёмом тёмных
// поверхностей и страничными переменными) + применение темы к <html>.

import { PRESETS, tokens, hexFor } from "./you";
import { invoke } from "@tauri-apps/api/core";

const STOCK_DARK: Record<string, string> = {
  primary: "#d0bcff", on_primary: "#371e73",
  primary_container: "#4f378b", on_primary_container: "#eaddff",
  secondary: "#ccc2dc", on_secondary: "#322e3e",
  secondary_container: "#4a4458", on_secondary_container: "#e8def8",
  surface: "#141218", on_surface: "#e6e0e9",
  on_surface_variant: "#cac4d0", outline: "#938f99", outline_variant: "#49454f",
  surface_lowest: "#0f0d13", surface_low: "#1d1b22",
  surface_container: "#211f26", surface_high: "#2b2930", surface_highest: "#36343b",
};

const STOCK_LIGHT: Record<string, string> = {
  primary: "#6750a4", on_primary: "#ffffff",
  primary_container: "#eaddff", on_primary_container: "#21005d",
  secondary: "#625b71", on_secondary: "#ffffff",
  secondary_container: "#e8def8", on_secondary_container: "#1d192b",
  surface: "#fffbfe", on_surface: "#1c1b1f",
  on_surface_variant: "#49454f", outline: "#79747e", outline_variant: "#cac4d0",
  surface_lowest: "#ffffff", surface_low: "#f7f2fa",
  surface_container: "#fffbfe", surface_high: "#ece6f0", surface_highest: "#e6e0e9",
};

function hexToRgb(hex: string): [number, number, number] {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
  if (!m) return [0, 0, 0];
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/** round() как в Python — половина округляется к чётному. */
function pyRound(x: number): number {
  const f = Math.floor(x);
  const r = x - f;
  if (r < 0.5) return f;
  if (r > 0.5) return f + 1;
  return f % 2 === 0 ? f : f + 1;
}

function mixHex(c1: string, c2: string, k: number): string {
  if (!/^#?[0-9a-f]{6}$/i.test(c1)) c1 = "#000000";
  if (!/^#?[0-9a-f]{6}$/i.test(c2)) c2 = "#000000";
  const [r1, g1, b1] = hexToRgb(c1);
  const [r2, g2, b2] = hexToRgb(c2);
  const q = (a: number, b: number) => pyRound(a * (1 - k) + b * k);
  return "#" + [q(r1, r2), q(g1, g2), q(b1, b2)]
    .map((x) => Math.max(0, Math.min(255, x)).toString(16).padStart(2, "0"))
    .join("");
}

/** Тёмные акценты дают почти-чёрные поверхности — подмешиваем нейтральную базу. */
function liftDark(base: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = { ...base };
  const st = STOCK_DARK;
  const pairs: Array<[string, string]> = [
    ["surface_lowest", st.surface_lowest],
    ["surface_low", st.surface_low],
    ["surface", st.surface],
    ["surface_high", st.surface_high],
    ["surface_highest", st.surface_highest],
    ["outline_variant", st.outline_variant],
  ];
  for (const [key, neutral] of pairs) {
    if (out[key]) out[key] = mixHex(out[key], neutral, 0.75);
  }
  return out;
}

function pageVars(base: Record<string, string>): Record<string, string> {
  return {
    title1: base.primary,
    title2: base.on_surface_variant,
    focus: base.primary_container,
    link: base.primary,
    mine: base.primary_container,
    mine_sender: base.on_primary_container,
    chat_sub: base.on_surface_variant,
    desk: base.surface_lowest,
    panel: base.surface_low,
    panel_hover: base.surface_high,
    divider: base.outline_variant,
    text1: base.on_surface,
    muted: base.on_surface_variant,
  };
}

export function m3Tokens(accent: string | null, dark: boolean): Record<string, string> {
  const a = (accent ?? "").toLowerCase();
  let base: Record<string, string>;
  if (a && a !== "" && a !== "purple" && a !== "default") {
    const t = tokens(hexFor(accent), dark);
    base = {
      primary: t["md-sys-color-primary"],
      on_primary: t["md-sys-color-on-primary"],
      primary_container: t["md-sys-color-primary-container"],
      on_primary_container: t["md-sys-color-on-primary-container"],
      secondary: t["md-sys-color-secondary"],
      on_secondary: t["md-sys-color-on-secondary"],
      secondary_container: t["md-sys-color-secondary-container"],
      on_secondary_container: t["md-sys-color-on-secondary-container"],
      on_surface: t["md-sys-color-on-surface"],
      on_surface_variant: t["md-sys-color-on-surface-variant"],
      outline: t["md-sys-color-outline"],
      outline_variant: t["md-sys-color-outline-variant"],
      surface_lowest: t["md-sys-color-surface-container-lowest"],
      surface_low: t["md-sys-color-surface-container-low"],
      // Внимание: в theme.py ключ "surface" задаётся дважды, последний побеждает:
      // "surface" = md-sys-color-surface-container (а не -surface).
      surface: t["md-sys-color-surface-container"],
      surface_high: t["md-sys-color-surface-container-high"],
      surface_highest: t["md-sys-color-surface-container-highest"],
    };
  } else {
    base = { ...(dark ? STOCK_DARK : STOCK_LIGHT) };
  }
  if (dark) base = liftDark(base);
  return { ...base, ...pageVars(base) };
}

const TOKEN_TO_VAR: Record<string, string> = {
  desk: "--desk", panel: "--panel", panel_hover: "--panel-hover", divider: "--divider",
  text1: "--text1", muted: "--muted", title1: "--title1", title2: "--title2",
  link: "--link", mine: "--mine", mine_sender: "--mine-sender", chat_sub: "--chat-sub",
  focus: "--focus",
  primary: "--primary", on_primary: "--on-primary",
  primary_container: "--primary-container", on_primary_container: "--on-primary-container",
  secondary: "--secondary", on_secondary: "--on-secondary",
  secondary_container: "--secondary-container", on_secondary_container: "--on-secondary-container",
  surface: "--surface", on_surface: "--on-surface", on_surface_variant: "--on-surface-variant",
  outline: "--outline", outline_variant: "--outline-variant",
  surface_lowest: "--surface-lowest", surface_low: "--surface-low",
  surface_high: "--surface-high", surface_highest: "--surface-highest",
  chat_sub2: "--chat-sub",
};

/** Применить тему: вешает data-theme/data-mode и CSS-переменные на <html>. */
export function applyTheme(theme: string, mode: string, accent: string): void {
  const root = document.documentElement;
  if (theme === "file") {
    const ft = fileTheme;
    if (ft) {
      if (ft.mode) mode = ft.mode;
      if (ft.accent) accent = ft.accent;
    }
  }
  root.dataset.theme = theme;
  root.dataset.mode = mode;
  if (theme !== "win98") {
    const t = m3Tokens(accent, mode === "dark");
    for (const [key, value] of Object.entries(t)) {
      const css = TOKEN_TO_VAR[key];
      if (css) root.style.setProperty(css, String(value));
    }
    if (theme === "file" && fileTheme?.colors) {
      for (const [key, value] of Object.entries(fileTheme.colors)) {
        const css = TOKEN_TO_VAR[key] ?? (key.startsWith("--") ? key : null);
        if (css) root.style.setProperty(css, value);
      }
    }
  }
}

/** Тема из файла (theme.json) — переопределяет любые токены темы. */
export type FileTheme = {
  name?: string;
  mode?: "dark" | "light";
  accent?: string;
  colors?: Record<string, string>;
};

let fileTheme: FileTheme | null = null;

export function getFileTheme(): FileTheme | null {
  return fileTheme;
}

export function loadFileTheme(t: FileTheme | null): void {
  fileTheme = t;
}

/** Токены, которые можно переопределить в theme.json (ключи TOKEN_TO_VAR). */
const THEME_KEYS = Object.keys(TOKEN_TO_VAR);

/** Прочитать %APPDATA%\nekochat\theme.json (в браузере/без Tauri вернёт null). */
export async function readFileTheme(): Promise<FileTheme | null> {
  try {
    const raw: string | null = await invoke<string | null>("read_theme_file");
    if (!raw) return null;
    const obj: unknown = JSON.parse(raw);
    if (!obj || typeof obj !== "object") return null;
    const ft = obj as FileTheme;
    if (typeof ft.name !== "string") ft.name = undefined;
    if (ft.mode !== "dark" && ft.mode !== "light") ft.mode = undefined;
    if (typeof ft.accent !== "string" || !/^#?[0-9a-f]{6}$/i.test(ft.accent)) ft.accent = undefined;
    const colors: Record<string, string> = {};
    if (ft.colors && typeof ft.colors === "object") {
      for (const [k, v] of Object.entries(ft.colors)) {
        if (typeof v === "string" && /^#[0-9a-f]{6}$/i.test(v) && (THEME_KEYS.includes(k) || k.startsWith("--"))) {
          colors[k] = v;
        }
      }
    }
    ft.colors = colors;
    return ft;
  } catch {
    return null;
  }
}

export type ThemeSettings = { theme: string; mode: string; accent: string };

export function defaultSettings(): ThemeSettings {
  return { theme: "material", mode: "dark", accent: "indigo" };
}

export { PRESETS };
export const ACCENT_NAMES = Object.keys(PRESETS);