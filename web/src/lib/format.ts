// Формат времени и цвет аватарки — портированы из desktop/src/format.ts.

import type { User } from "./types";

/** Палитра аватарок: та же, что в десктопе, чтобы пользователи выглядели
 *  одинаково на разных клиентах. */
const AV_COLORS = [
  "#e91e63", "#9c27b0", "#673ab7", "#3f51b5", "#2196f3",
  "#00bcd4", "#009688", "#4caf50", "#ff9800", "#f44336",
];

let crcTable: Uint32Array | null = null;
function crcTableInit(): Uint32Array {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
}

export function crc32(s: string): number {
  if (!crcTable) crcTable = crcTableInit();
  const t = crcTable;
  let c = 0xffffffff;
  for (let i = 0; i < s.length; i++) c = (t[(c ^ s.charCodeAt(i)) & 0xff] as number) ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

/** Стабильный цвет по нику: одинаковый на всех клиентах. */
export function userColor(u: Partial<User> | null | undefined): string {
  const c = u && u.profile_color;
  if (typeof c === "string" && /^#[0-9a-f]{6}$/i.test(c)) return c;
  const name = (u && u.username) || "?";
  return AV_COLORS[crc32(name) % AV_COLORS.length] as string;
}

export function avatarColors(): string[] {
  return AV_COLORS;
}

/** Русское согласование: участник / участника / участников.
 *  Ключи считаются по последним двум цифрам: 11-14 всегда идут во множественном
 *  числе (11 участников, а не 11 участников). */
export function plural(n: number, one: string, few: string, many: string): string {
  const a = Math.abs(n) % 100;
  const b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b > 1 && b < 5) return few;
  if (b === 1) return one;
  return many;
}

/** «3 участника», «1 участник» — число вместе со словом. */
export function pluralized(n: number, one: string, few: string, many: string): string {
  return `${n} ${plural(n, one, few, many)}`;
}

export function fmtTime(s: string | undefined | null): string {  try {
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
