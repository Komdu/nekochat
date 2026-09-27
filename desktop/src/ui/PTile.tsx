import type { CSSProperties } from "react";
import { userColor } from "../format";
import type { User } from "../types";

/**
 * Квадратная плитка с буквой — как на макете клиента: участники комнаты
 * в нижней панели. В отличие от Avatar (круг) — квадратная, с рамкой.
 */
export function PTile({
  user,
  size = 30,
  online,
  onClick,
  title,
  className = "",
}: {
  user?: Partial<User> | null;
  size?: number;
  online?: boolean;
  onClick?: (() => void) | undefined;
  title?: string;
  className?: string;
}) {
  const name = (user && (user.display_name || user.username)) || "?";
  const letter = (name[0] || "?").toUpperCase();
  const style: CSSProperties = {
    width: size,
    height: size,
    background: userColor(user),
    color: "#ffffff",
    fontSize: Math.max(11, Math.round(size * 0.44)),
    fontWeight: 700,
  };
  const label = title ?? name;
  const tile = (
    <span className={"ptile-el" + (online === false ? " off" : "") + (className ? " " + className : "")} style={style} title={label}>
      {letter}
    </span>
  );
  if (!onClick) return tile;
  return (
    <button className="ptile-btn" onClick={onClick} title={label} aria-label={label}>
      {tile}
    </button>
  );
}
