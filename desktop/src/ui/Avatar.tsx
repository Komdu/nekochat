import { useState } from "react";
import type { CSSProperties } from "react";
import { userColor } from "../format";
import { useStore } from "../store";
import type { User } from "../types";

export function Avatar({
  user,
  size = 32,
  online,
  className = "",
  ringColor,
}: {
  user?: Partial<User> | null;
  size?: number;
  online?: boolean;
  className?: string;
  ringColor?: string | null;
}) {
  const { api } = useStore();
  const [imgErr, setImgErr] = useState(false);
  const name = (user && (user.display_name || user.username)) || "?";
  const letter = (name[0] || "?").toUpperCase();
  const color = userColor(user);
  const radius = "50%";
  const style: CSSProperties = {
    width: size,
    height: size,
    borderRadius: radius,
    background: color,
    color: "#ffffff",
    fontSize: Math.max(10, Math.round(size * 0.46)),
    fontWeight: 700,
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    position: "relative",
    flex: "none",
    userSelect: "none",
  };
  if (ringColor) {
    style.boxShadow = `0 0 0 2px ${ringColor}`;
  }
  return (
    <span className={`avatar-el ${className}`} style={style}>
      {user && (user as any).avatar && !imgErr ? (
        <img
          src={api ? api.avatarUrl((user as any).avatar) : ""}
          alt=""
          style={{ width: "100%", height: "100%", objectFit: "cover", display: "block", borderRadius: "inherit" }}
          onError={() => setImgErr(true)}
        />
      ) : (
        <span>{letter}</span>
      )}
      {online !== undefined && (
        <span
          className="online-dot"
          style={{
            position: "absolute",
            right: -1,
            bottom: -1,
            width: Math.max(7, Math.round(size * 0.28)),
            height: Math.max(7, Math.round(size * 0.28)),
            borderRadius: "50%",
            background: online ? "#31c66d" : "#9aa0a6",
            boxShadow: "0 0 0 2px var(--panel)",
          }}
        />
      )}
    </span>
  );
}