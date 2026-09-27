// Точный порт client_ui/you.py: Material You — M3-палитра из акцента (OKLCH).

export const PRESETS: Record<string, string> = {
  purple: "#6750a4",
  indigo: "#283593",
  blue: "#1565c0",
  teal: "#00695c",
  green: "#1b5e20",
  pink: "#ad1457",
  red: "#b71c1c",
  orange: "#bf360c",
};

const HEX = /^#?([0-9a-f]{6})$/i;

function unrgb(v: number): number {
  v /= 255;
  return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
}

export function srcLch(hex: string): [number, number, number] {
  const m = HEX.exec(typeof hex === "string" ? hex : "");
  if (!m) return [0.45, 0.17, 275.0];
  const n = parseInt(m[1], 16);
  const r = unrgb((n >> 16) & 255),
    g = unrgb((n >> 8) & 255),
    b = unrgb(n & 255);
  const l_ = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const mm = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  const L = 0.2104542553 * l_ + 0.793617785 * mm - 0.0040720468 * s;
  const a = 1.9779984951 * l_ - 2.428592205 * mm + 0.4505937099 * s;
  const bb = 0.0259040371 * l_ + 0.7827717662 * mm - 0.808675766 * s;
  return [L, Math.hypot(a, bb), (Math.atan2(bb, a) * 180) / Math.PI];
}

function clamp01(x: number): number {
  return Math.max(0, Math.min(1, x));
}

export function tone(L: number, C: number, h: number): string {
  for (let i = 0; i < 30; i++) {
    const a = C * Math.cos((h * Math.PI) / 180);
    const b = C * Math.sin((h * Math.PI) / 180);
    const l_ = L + 0.3963377774 * a + 0.2158037573 * b;
    const m_ = L - 0.1055613458 * a - 0.0638541728 * b;
    const s_ = L - 0.0894841775 * a - 1.291485548 * b;
    const l = Math.pow(l_, 3),
      m = Math.pow(m_, 3),
      s = Math.pow(s_, 3);
    const R = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s;
    const G = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s;
    const B = -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s;
    if (
      R >= -0.0005 && R <= 1.0005 &&
      G >= -0.0005 && G <= 1.0005 &&
      B >= -0.0005 && B <= 1.0005
    ) {
      let out = "#";
      for (const x of [R, G, B]) {
        const y = clamp01(x) <= 0.0031308 ? 12.92 * clamp01(x) : 1.055 * Math.pow(clamp01(x), 1 / 2.4) - 0.055;
        out += Math.max(0, Math.min(255, Math.round(y * 255))).toString(16).padStart(2, "0");
      }
      return out;
    }
    C *= 0.93;
    if (C < 0.002) break;
  }
  return "#888888";
}

export function lum(hex: string): number {
  const m = HEX.exec(hex || "");
  if (!m) return 1.0;
  const n = parseInt(m[1], 16);
  const f = (c: number): number => {
    c = c / 255;
    return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * f((n >> 16) & 255) + 0.7152 * f((n >> 8) & 255) + 0.0722 * f(n & 255);
}

export function tokens(hex: string, dark: boolean): Record<string, string> {
  const [L, c0, h] = srcLch(hex);
  const C = Math.max(0.1, Math.min(0.2, c0));
  const sc = (f: number) => C * f;
  const t: Record<string, string> = {};
  const set = (k: string, v: string) => {
    t[k] = v;
  };

  set("md-sys-color-primary", dark ? tone(0.8, sc(1), h) : tone(0.45, sc(1), h));
  set("md-sys-color-on-primary", dark ? tone(0.22, sc(0.6), h) : "#ffffff");
  set("md-sys-color-primary-container", dark ? tone(0.3, sc(0.7), h) : tone(0.9, sc(0.7), h));
  set("md-sys-color-on-primary-container", dark ? tone(0.88, sc(0.8), h) : tone(0.15, sc(0.8), h));
  set("md-sys-color-secondary", dark ? tone(0.8, sc(0.7), h) : tone(0.45, sc(0.7), h));
  set("md-sys-color-on-secondary", dark ? tone(0.22, sc(0.5), h) : "#ffffff");
  set("md-sys-color-secondary-container", dark ? tone(0.3, sc(0.5), h) : tone(0.9, sc(0.5), h));
  set("md-sys-color-on-secondary-container", dark ? tone(0.88, sc(0.7), h) : tone(0.15, sc(0.7), h));
  set("md-sys-color-surface", dark ? tone(0.17, sc(0.1), h) : tone(0.98, sc(0.1), h));
  set("md-sys-color-on-surface", dark ? tone(0.94, sc(0.14), h) : tone(0.13, sc(0.14), h));
  set("md-sys-color-on-surface-variant", dark ? tone(0.8, sc(0.16), h) : tone(0.31, sc(0.16), h));
  set("md-sys-color-outline", dark ? tone(0.62, sc(0.16), h) : tone(0.45, sc(0.16), h));
  set("md-sys-color-outline-variant", dark ? tone(0.3, sc(0.14), h) : tone(0.85, sc(0.14), h));
  set("md-sys-color-surface-container-lowest", dark ? tone(0.06, sc(0.08), h) : tone(1.0, sc(0.08), h));
  set("md-sys-color-surface-container-low", dark ? tone(0.14, sc(0.1), h) : tone(0.97, sc(0.1), h));
  set("md-sys-color-surface-container", dark ? tone(0.17, sc(0.11), h) : tone(0.98, sc(0.11), h));
  set("md-sys-color-surface-container-high", dark ? tone(0.21, sc(0.13), h) : tone(0.95, sc(0.13), h));
  set("md-sys-color-surface-container-highest", dark ? tone(0.26, sc(0.16), h) : tone(0.92, sc(0.16), h));

  set("title1", dark ? tone(0.42, sc(1), h) : tone(0.45, sc(1), h));
  set("title2", dark ? tone(0.58, sc(0.9), h) : tone(0.62, sc(0.9), h));
  set("focus", dark ? tone(0.3, sc(0.45), h) : tone(0.93, sc(0.5), h));
  set("link", dark ? tone(0.8, sc(1), h) : tone(0.45, sc(1), h));
  set("mine", dark ? tone(0.3, sc(0.7), h) : tone(0.9, sc(0.7), h));
  set("mine-sender", dark ? tone(0.88, sc(0.8), h) : tone(0.15, sc(0.8), h));
  set("chat-sub", dark ? tone(0.9, sc(0.4), h) : tone(0.86, sc(0.4), h));
  set("desk", dark ? tone(0.11, sc(0.1), h) : tone(0.95, sc(0.1), h));
  set("panel", dark ? tone(0.17, sc(0.12), h) : tone(0.98, sc(0.12), h));
  set("panel-hover", dark ? tone(0.24, sc(0.15), h) : tone(0.94, sc(0.15), h));
  set("divider", dark ? tone(0.32, sc(0.15), h) : tone(0.89, sc(0.15), h));
  set("text1", dark ? tone(0.94, sc(0.14), h) : tone(0.13, sc(0.14), h));
  set("muted", dark ? tone(0.74, sc(0.14), h) : tone(0.42, sc(0.14), h));
  set("win-text", t["text1"]);

  if (!dark) {
    for (let i = 0; i < 6; i++) {
      if (lum(t["md-sys-color-primary"]) <= 0.17) break;
      const [nL] = srcLch(t["md-sys-color-primary"]);
      t["md-sys-color-primary"] = tone(Math.max(0.3, nL - 0.04), sc(1), h);
    }
  }
  return t;
}

export function hexFor(v: string | null | undefined): string {
  if (typeof v === "string" && HEX.test(v)) return v;
  return PRESETS[v ?? ""] ?? PRESETS.purple;
}