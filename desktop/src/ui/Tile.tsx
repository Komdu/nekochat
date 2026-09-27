import { userColor } from "../format";

/** Скруглённый квадрат-плитка (стиль лендинга) — для комнат в сайдбаре. */
export function Tile({ name, size = 30, className = "" }: { name: string; size?: number; className?: string }) {
  const color = userColor({ username: name } as any);
  return (
    <span
      className={`tile-el ${className}`}
      style={{
        width: size,
        height: size,
        borderRadius: Math.round(size * 0.32),
        background: color,
        color: "#fff",
        fontSize: Math.max(11, Math.round(size * 0.5)),
        fontWeight: 700,
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        flex: "none",
        userSelect: "none",
      }}
    >
      #
    </span>
  );
}