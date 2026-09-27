// ---- утилиты, портированные из client_ui/chat.py ----

const AV_COLORS = [
  "#e91e63", "#9c27b0", "#673ab7", "#3f51b5", "#2196f3",
  "#00bcd4", "#009688", "#4caf50", "#ff9800", "#f44336",
];

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

export function crc32(s: string): number {
  let c = 0xffffffff;
  for (let i = 0; i < s.length; i++) {
    c = CRC_TABLE[(c ^ s.charCodeAt(i)) & 0xff] ^ (c >>> 8);
  }
  return (c ^ 0xffffffff) >>> 0;
}

/** Стабильный хэш строки — как zlib.crc32 в нативном клиенте. */
export function stableColorKey(...parts: Array<string | number | null | undefined>): number {
  return crc32(parts.map((p) => String(p ?? "")).join("|"));
}

export function userColor(u: Partial<UserLike> | null | undefined): string {
  const c = u && (u as any).profile_color;
  if (typeof c === "string" && /^#[0-9a-f]{6}$/i.test(c)) return c;
  const name = (u && (u as any).username) || "?";
  return AV_COLORS[stableColorKey(name) % AV_COLORS.length];
}

export function avatarColors(): string[] {
  return AV_COLORS;
}

interface UserLike {
  profile_color?: string | null;
  username?: string;
}

export function fmtTime(s: string | undefined | null): string {
  try {
    const dt = new Date(s ? s.replace("Z", "+00:00") : "");
    if (isNaN(dt.getTime())) return "";
    const local = new Date(dt.getTime());
    const now = new Date();
    const sameDay =
      local.getFullYear() === now.getFullYear() &&
      local.getMonth() === now.getMonth() &&
      local.getDate() === now.getDate();
    const pad = (x: number) => String(x).padStart(2, "0");
    if (sameDay) return `${pad(local.getHours())}:${pad(local.getMinutes())}`;
    return `${pad(local.getDate())}.${pad(local.getMonth() + 1)} ${pad(local.getHours())}:${pad(local.getMinutes())}`;
  } catch {
    return "";
  }
}

export function nowIso(): string {
  const d = new Date();
  const pad = (x: number) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}