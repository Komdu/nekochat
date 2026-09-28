<script lang="ts">
  // Аватарка: серверная картинка или инициал на стабильном цвете по нику.
  // Цвет берётся из format.ts — тот же crc32, что в десктопе, поэтому у одного
  // человека аватарка одинаковая во всех клиентах.
  import { userColor } from "../lib/format";
  import type { User } from "../lib/types";

  let {
    user,
    size = 32,
    base = "",
  }: {
    user?: Partial<User> | null;
    size?: number;
    /** базовый URL для /avatars/... — передаём из стора */
    base?: string;
  } = $props();

  const src = $derived(
    user?.avatar && base ? `${base}/avatars/${encodeURIComponent(user.avatar)}` : "",
  );
  const initials = $derived(
    (user?.display_name || user?.username || "?").trim().slice(0, 2).toUpperCase(),
  );
  const bg = $derived(userColor(user));
  const color = $derived(bg);
  const dim = $derived(color.replace("#", "") + "00");
</script>

<div
  class="avatar"
  style={`width:${size}px;height:${size}px;background:linear-gradient(160deg,${bg},${dim});`}
  title={user?.display_name || user?.username || ""}
>
  {#if src}
    <img {src} alt="" onerror={(e) => ((e.currentTarget as HTMLImageElement).style.display = "none")} />
  {:else}
    <span style={`font-size:${Math.round(size * 0.4)}px`}>{initials}</span>
  {/if}
</div>

<style>
  .avatar {
    flex: none;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #fff;
    font-weight: 700;
    overflow: hidden;
    user-select: none;
  }
  .avatar img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
</style>
