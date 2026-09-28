<script lang="ts">
  // Оверлей звонка: входящий/исходящий/канал/завершён + панели демонстраций
  // экрана. Логика вся в движке (lib/calls.ts) — здесь только отображение.
  import { store } from "../lib/store.svelte";
  import Avatar from "./Avatar.svelte";
  import Icon from "./Icon.svelte";

  let screenFull = $state(false);

  const call = $derived(store.call);
  const phase = $derived(call?.phase ?? "idle");
  const isChannel = $derived(!!call && call.roomId != null);
  // движок в participants держит только чужих (себя не добавляет)
  const members = $derived(isChannel ? (call?.participants ?? []) : []);

  // тик для секундомера
  let now = $state(Date.now());
  $effect(() => {
    if (phase !== "active") return;
    const t = window.setInterval(() => (now = Date.now()), 1000);
    return () => window.clearInterval(t);
  });

  const dur = $derived.by(() => {
    if (!call?.startedAt) return "00:00";
    const s = Math.max(0, Math.floor((now - call.startedAt) / 1000));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  });

  // холсты демонстраций: 1-1 — один, канал — по холсту на показывающего.
  // Регистрируем элемент в движке, когда он появляется в DOM.
  let canvasRef = $state<HTMLCanvasElement | null>(null);
  let key = $state("");
  $effect(() => {
    const c = call;
    if (!c || c.phase !== "active") {
      store.calls?.setScreenCanvas(null, null);
      return;
    }
    const want = isChannel
      ? members.filter((p) => p.screen).map((p) => String(p.id))
      : c.screenActive && c.peerId != null
        ? [String(c.peerId)]
        : [];
    key = want.join(",");
    if (canvasRef) store.calls?.setScreenCanvas(isChannel ? null : (c.peerId ?? null), canvasRef);
  });

  function displayName(id: number | null | undefined): string {
    if (id == null) return "…";
    const u = store.usersMap[id];
    return u?.display_name || u?.username || `@${id}`;
  }

  let title = $derived.by(() => {
    if (!call) return "";
    if (isChannel) {
      const r = store.rooms.find((x) => String(x.id) === String(call?.roomId));
      return r ? r.name : "Голосовой канал";
    }
    return displayName(call.peerId);
  });

  let avatarUser = $derived.by(() => {
    if (!call) return undefined;
    if (isChannel) return call.inviterId != null ? store.usersMap[call.inviterId] : undefined;
    return call.peerId != null ? store.usersMap[call.peerId] : undefined;
  });
</script>

{#if call && phase !== "idle"}
  <div class="call-overlay">
    <div class="call-card phase-{phase}">
      <Avatar user={avatarUser} size={64} base={store.base} />
      <div class="call-name">{title}</div>

      {#if isChannel && phase === "incoming"}
        <div class="call-info">{displayName(call.inviterId)} приглашает в голосовой канал</div>
      {:else if !isChannel && phase === "incoming"}
        <div class="call-info">Входящий звонок…</div>
      {:else if phase === "outgoing"}
        <div class="call-info">Вызов…</div>
      {:else if phase === "connecting"}
        <div class="call-info">{isChannel ? "Вход в голосовой канал…" : "Соединение…"}</div>
      {:else if phase === "active"}
        <div class="call-info call-timer">
          {dur}
          {#if isChannel && members.length > 0}
            <span class="call-tag">в канале: {members.length + 1}</span>
          {/if}
          {#if call.muted}<span class="call-tag">микрофон выкл</span>{/if}
        </div>
      {:else if phase === "ended"}
        <div class="call-info">{call.reason}</div>
      {/if}

      {#if isChannel && (phase === "active" || phase === "connecting")}
        <div class="call-members">
          {#each members as p (p.id)}
            <div class="call-member">
              <Avatar user={store.usersMap[p.id]} size={32} base={store.base} />
              <div class="call-member-name">{displayName(p.id)}</div>
              {#if p.screen}<div class="call-member-screen"><Icon name="monitor" size={16} /></div>{/if}
              <div class="call-member-dot"></div>
            </div>
          {/each}
          {#if members.length === 0}
            <div class="call-info">Пока никого — подожди, скоро подтянутся</div>
          {/if}
        </div>
      {/if}

      <div class="call-actions">
        {#if phase === "incoming"}
          <button class="call-btn call-decline" onclick={() => store.calls?.decline()}>
            {isChannel ? "Позже" : "Отклонить"}
          </button>
          <button class="call-btn call-accept" onclick={() => store.calls?.accept()}>
            {isChannel ? "Войти" : "Принять"}
          </button>
        {:else if phase === "active"}
          <button
            class="call-btn call-mute"
            class:call-mute-on={call.muted}
            onclick={() => store.calls?.toggleMute()}
            title={call.muted ? "Включить микрофон" : "Выключить микрофон"}
          >
            <Icon name={call.muted ? "micOff" : "mic"} size={17} />
          </button>
          {#if phase === "active"}
            <button
              class="call-btn call-screen"
              class:call-screen-on={call.screenOn}
              onclick={() => (call?.screenOn ? store.calls?.stopScreenShare() : void store.calls?.startScreenShare())}
              title={call?.screenOn ? "Остановить демонстрацию экрана" : "Демонстрация экрана"}
            >
              {#if call?.screenOn}
                <Icon name="stop" size={14} /><Icon name="monitor" size={15} />
              {:else}
                <Icon name="monitor" size={15} />
              {/if}
            </button>
          {/if}
          <button class="call-btn call-decline" onclick={() => store.calls?.hangup()}>
            {isChannel ? "Выйти" : "Завершить"}
          </button>
        {:else if phase === "ended"}
          <button class="call-btn call-neutral" onclick={() => store.calls?.dismiss()}>Ок</button>
        {/if}
      </div>

      {#if call.screenError && phase === "active"}
        <div class="call-info call-screen-error">{call.screenError}</div>
      {/if}
    </div>

    <!-- демонстрации экрана -->
    {#if isChannel && phase === "active"}
      {#each members.filter((p) => p.screen) as p (p.id)}
        <div class="call-screen-panel">
          <div class="call-screen-head">
            <span class="call-screen-title"><Icon name="monitor" size={15} /> {displayName(p.id)}</span>
          </div>
          <canvas class="call-screen-canvas" data-peer={p.id}></canvas>
        </div>
      {/each}
    {:else if !isChannel && call.screenActive && phase === "active"}
      <div class="call-screen-panel" class:full={screenFull}>
        <div class="call-screen-head">
          <span class="call-screen-title"><Icon name="monitor" size={15} /> Демонстрация экрана</span>
          <button class="call-btn call-neutral" onclick={() => (screenFull = !screenFull)}>
            {screenFull ? "Свернуть" : "На весь экран"}
          </button>
        </div>
        <canvas class="call-screen-canvas" bind:this={canvasRef}></canvas>
      </div>
    {/if}
  </div>
{/if}

<style>
  .call-overlay {
    position: fixed;
    inset: 0;
    z-index: 200;
    background: rgba(0, 0, 0, 0.55);
    display: flex;
    align-items: center;
    justify-content: center;
    backdrop-filter: blur(3px);
  }
  .call-card {
    min-width: 300px;
    max-width: calc(100vw - 40px);
    background: var(--surface-high);
    border: 1px solid var(--outline-variant);
    border-radius: 20px;
    padding: 26px 30px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
    box-shadow: 0 24px 70px rgba(0, 0, 0, 0.55);
    color: var(--text1);
    text-align: center;
  }
  .call-name {
    font-size: 18px;
    font-weight: 700;
  }
  .call-info {
    font-size: 14px;
    color: var(--muted);
    min-height: 20px;
  }
  .call-timer {
    display: inline-flex;
    gap: 8px;
    align-items: center;
    font-variant-numeric: tabular-nums;
  }
  .call-tag {
    color: var(--title1);
  }
  .call-actions {
    display: flex;
    gap: 10px;
    margin-top: 6px;
  }
  .call-btn {
    border: none;
    border-radius: 999px;
    padding: 9px 20px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    color: #fff;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    transition: filter 0.15s;
  }
  .call-btn:hover {
    filter: brightness(1.12);
  }
  .call-btn:active {
    filter: brightness(0.92);
  }
  .call-accept {
    background: #2e7d32;
  }
  .call-decline {
    background: #b3261e;
  }
  .call-mute {
    background: var(--secondary-container);
    color: var(--on-secondary-container);
  }
  .call-mute-on {
    background: #e5f68b;
    color: #1a1604;
  }
  .call-neutral {
    background: var(--surface-highest);
    color: var(--text1);
    border: 1px solid var(--outline-variant);
  }
  .call-screen {
    background: var(--secondary-container);
    color: var(--on-secondary-container);
  }
  .call-screen-on {
    background: #b3261e;
    color: #fff;
  }
  .call-screen-error {
    color: var(--title1);
    font-size: 13px;
    max-width: 260px;
  }

  .call-screen-panel {
    position: absolute;
    right: 24px;
    bottom: 24px;
    z-index: 210;
    width: min(420px, 38vw);
    min-width: 260px;
    background: rgba(0, 0, 0, 0.78);
    border: 1px solid rgba(255, 255, 255, 0.25);
    border-radius: 14px;
    overflow: hidden;
    box-shadow: 0 18px 50px rgba(0, 0, 0, 0.55);
    backdrop-filter: blur(4px);
  }
  .call-screen-panel.full {
    right: 0;
    bottom: 0;
    width: 100%;
    height: 100%;
    border-radius: 0;
    display: flex;
    flex-direction: column;
  }
  .call-screen-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    color: #fff;
    font-size: 13px;
    font-weight: 600;
  }
  .call-screen-title {
    display: inline-flex;
    align-items: center;
    gap: 7px;
  }
  .call-screen-canvas {
    display: block;
    width: 100%;
    max-height: 260px;
    background: #000;
    object-fit: contain;
  }
  .call-screen-panel.full .call-screen-canvas {
    max-height: calc(100vh - 48px);
  }

  .call-members {
    display: flex;
    flex-direction: column;
    gap: 8px;
    width: 100%;
    max-height: 200px;
    overflow-y: auto;
    padding: 4px 2px;
  }
  .call-member {
    display: flex;
    align-items: center;
    gap: 10px;
    background: var(--surface-highest);
    border: 1px solid var(--outline-variant);
    border-radius: 12px;
    padding: 6px 10px;
    text-align: left;
  }
  .call-member-name {
    font-size: 14px;
    font-weight: 600;
    color: var(--text1);
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .call-member-screen {
    font-size: 14px;
  }
  .call-member-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #66bb6a;
    flex: none;
  }
</style>
