<script lang="ts">
  // Чат: список чатов слева, сообщения справа. Плоская тёмная тема.
  import { store } from "../lib/store.svelte";
  import { fmtTime } from "../lib/format";
  import Avatar from "./Avatar.svelte";
  import Icon from "./Icon.svelte";
  import Dialog from "./Dialog.svelte";
  import Settings from "./Settings.svelte";
  import CreateRoom from "./CreateRoom.svelte";
  import FilesPanel from "./FilesPanel.svelte";

  let draft = $state("");
  let showSettings = $state(false);
  let showCreate = $state(false);

  /** Файлы прикрепляются скрепкой. Диалог нативный — он работает везде. */
  let sending = $state(false);
  async function pickFile(e: Event) {
    const input = e.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    input.value = "";
    if (!file) return;
    sending = true;
    try {
      await store.sendFile(file);
    } catch (err) {
      store.noteMsg(err instanceof Error ? err.message : String(err));
    } finally {
      sending = false;
    }
  }

  const msgs = $derived(store.messages);
  const cur = $derived(store.current);

  function send(e: Event) {
    e.preventDefault();
    const t = draft.trim();
    if (!t) return;
    store.send(t);
    draft = "";
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(e);
    }
  }

  // Автор сообщения. У комнатных сообщений сервер отдаёт только вложенный
  // объект `user` (поля user_id нет), у личных — `sender`/`sender_id`.
  // Поэтому проверяем все четыре варианта, иначе «мои» сообщения не
  // отличаются от чужих и всё рисуется в одну сторону.
  type AnyMsg = {
    sender_id?: number;
    user_id?: number;
    sender?: { id?: number; display_name?: string | null; username?: string };
    user?: { id?: number; display_name?: string | null; username?: string };
  };

  function authorId(m: AnyMsg): number | undefined {
    return m.sender_id ?? m.user_id ?? m.sender?.id ?? m.user?.id;
  }

  function who(m: AnyMsg): string {
    const uid = authorId(m);
    if (uid === store.me?.id) return store.me?.display_name || store.me?.username || "Я";
    const u = m.sender ?? m.user;
    return u?.display_name || u?.username || (uid != null ? "@" + uid : "?");
  }

  function isMine(m: AnyMsg): boolean {
    return authorId(m) === store.me?.id;
  }
</script>

<div class="app">
  <aside class="side">
    <div class="side-head">
      <span class="side-logo">#</span>
      <div class="side-server">
        <div class="server-name">nekochat</div>
        <div class="server-sub">{store.onlineCount} онлайн</div>
      </div>
      <button class="icon-btn" title="Создать комнату" onclick={() => (showCreate = true)}>
        <Icon name="plus" size={16} />
      </button>
      <button class="icon-btn" title="Обновить" onclick={() => window.location.reload()}>
        <Icon name="refresh" size={16} />
      </button>
    </div>
    <div class="list">
      {#each store.list as item (item.kind + item.id)}
        <button
          class="list-item"
          class:active={cur?.kind === item.kind && cur?.id === item.id}
          onclick={() => (item.kind === "room"
            ? store.selectRoom(item.room ?? { id: Number(item.id), name: item.label })
            : store.selectUser(item.user ?? { id: Number(item.id), username: item.label, display_name: item.label }))}
        >
          <!-- личные чаты показываем аватаркой, комнаты — решёткой -->
          {#if item.user}
            <span class="item-avatar">
              <Avatar user={item.user} size={28} base={store.base} />
              {#if store.isOnline(item.user)}<span class="item-online"></span>{/if}
            </span>
          {:else}
            <span class="item-mark">#</span>
          {/if}
          <span class="item-info">
            <span class="item-name">{item.label}</span>
            <span class="item-sub">{item.sub}</span>
          </span>
        </button>
      {/each}
      {#if store.list.length === 0}
        <div class="empty">Пока пусто — создайте комнату</div>
      {/if}
    </div>
    <div class="side-foot">
      <Avatar user={store.me} size={28} base={store.base} />
      <div class="me-box">
        <button class="me-name" title="Настройки" onclick={() => (showSettings = true)}>
          {store.me?.display_name || store.me?.username}
        </button>
        <!-- свой статус меняется прямо тут: не нужно лезть в настройки,
             чтобы сказать «играю во что-то» -->
        <input
          class="me-status"
          value={store.me?.status ?? ""}
          maxlength="100"
          placeholder="что делаешь? например: играю в X"
          onchange={(e) => store.setMyStatus((e.currentTarget as HTMLInputElement).value)}
          onkeydown={(e) => {
            if (e.key === "Enter") (e.currentTarget as HTMLInputElement).blur();
          }}
        />
      </div>
      <button class="icon-btn" title="Настройки" onclick={() => (showSettings = true)}>
        <Icon name="settings" size={16} />
      </button>
      <button class="icon-btn" title="Выйти" onclick={() => store.logout()}>
        <Icon name="power" size={16} />
      </button>
    </div>
  </aside>

  <main class="chat">
    <header class="chat-head">
      {#if cur}
        <div class="chat-title">
          <span class="chan-chip">{cur.kind === "room" ? "#" : "@"}</span>
          <div class="title-box">
            <span class="title-text">{cur.label.replace(/^[@#]\s*/, "")}</span>
            {#if cur.kind === "dm" && store.usersMap[Number(cur.id)]?.status}
              <!-- в шапке статус важнее: это то, за чем человек и открыл чат -->
              <span class="title-status">{store.usersMap[Number(cur.id)]?.status}</span>
            {/if}
          </div>
          {#if cur.kind === "dm" && store.usersMap[Number(cur.id)]}
            <span class="online-dot" class:on={store.isOnline(store.usersMap[Number(cur.id)])}></span>
          {/if}
        </div>
        <div class="head-actions">
          <button
            class="head-btn"
            class:active={store.call?.roomId != null && String(store.call.roomId) === cur.id}
            title={cur.kind === "room" ? "Голосовой канал" : "Позвонить"}
            onclick={() => {
              if (cur.kind === "room") store.joinRoomCall(Number(cur.id));
              else store.callPeer(store.usersMap[Number(cur.id)] || { id: Number(cur.id), username: "?" });
            }}
          >
            <Icon name={cur.kind === "room" ? "users" : "phone"} size={17} />
          </button>
        </div>
      {:else}
        <div class="chat-title"><span class="title-text">nekochat</span></div>
      {/if}
    </header>

    {#if store.note}<div class="note-bar">{store.note}</div>{/if}

    <div class="msgs">
      {#if !cur}
        <div class="placeholder">Выбери комнату или собеседника слева</div>
      {:else if msgs.length === 0}
        <div class="placeholder">Пока пусто. Напиши первым!</div>
      {:else}
        {#each msgs as m (String(m.id ?? Math.random()))}
          <div class="msg" class:mine={isMine(m)}>
            <div class="msg-body">
              <div class="msg-head">
                <span class="msg-name">{who(m)}</span>
                <span class="msg-time">{fmtTime(m.created_at)}</span>
              </div>
              <div class="msg-text">{m.content}</div>
            </div>
          </div>
        {/each}
      {/if}
    </div>

    <FilesPanel />

    <div class="composer">
      <label class="clip" class:disabled={!cur} title="Прикрепить файл">
        <Icon name="mail" size={17} />
        {#if sending}<span class="clip-spin"></span>{/if}
        <input type="file" disabled={!cur} onchange={pickFile} />
      </label>
      <textarea
        class="composer-input"
        rows="1"
        bind:value={draft}
        onkeydown={onKeydown}
        placeholder={cur ? "Сообщение…" : "Сначала выбери чат"}
        disabled={!cur}
      ></textarea>
    </div>
  </main>
</div>

<Settings bind:open={showSettings} />
<CreateRoom bind:open={showCreate} />

<style>
  .app {
    display: flex;
    height: 100%;
  }

  /* ---------- список чатов ---------- */
  .side {
    width: 260px;
    flex: none;
    background: var(--panel);
    border-right: 1px solid var(--outline-variant);
    display: flex;
    flex-direction: column;
    padding: 12px 10px;
    gap: 8px;
  }
  .side-head {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 2px 6px 8px;
  }
  .side-logo {
    width: 32px;
    height: 32px;
    border-radius: 10px;
    background: var(--primary);
    color: var(--on-primary);
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 800;
    font-size: 16px;
    flex: none;
  }
  .side-server {
    min-width: 0;
    flex: 1;
  }
  .server-name {
    font-size: 14px;
    font-weight: 700;
  }
  .server-sub {
    font-size: 11px;
    color: var(--muted);
  }
  .icon-btn {
    width: 32px;
    height: 32px;
    border-radius: 999px;
    color: var(--muted);
    font-size: 15px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
  .icon-btn:hover {
    background: var(--panel-hover);
    color: var(--text1);
  }
  .list {
    flex: 1;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .list-item {
    display: flex;
    align-items: center;
    gap: 9px;
    width: 100%;
    text-align: left;
    padding: 7px 9px;
    border-radius: 12px;
    color: var(--text1);
  }
  .list-item:hover {
    background: var(--panel-hover);
  }
  .list-item.active {
    background: var(--primary-container);
    color: var(--on-primary-container);
  }
  .item-mark {
    width: 22px;
    height: 22px;
    border-radius: 7px;
    background: var(--surface-highest);
    color: var(--muted);
    font-size: 12px;
    font-weight: 700;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex: none;
  }
  /* аватарка в списке: 28px, как и круг, но с точкой «в сети» в углу */
  .item-avatar {
    position: relative;
    flex: none;
    display: inline-flex;
  }
  .item-online {
    position: absolute;
    right: -1px;
    bottom: -1px;
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: var(--ok);
    box-shadow: 0 0 0 2px var(--panel);
  }
  .list-item.active .item-mark {
    background: var(--primary);
    color: var(--on-primary);
  }
  .item-info {
    min-width: 0;
    display: flex;
    flex-direction: column;
  }
  .item-name {
    font-size: 13.5px;
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .item-sub {
    font-size: 11px;
    color: var(--muted);
  }
  .list-item.active .item-sub {
    color: var(--on-primary-container);
    opacity: 0.75;
  }
  .empty {
    color: var(--muted);
    font-size: 13px;
    text-align: center;
    padding: 20px 8px;
  }
  .side-foot {
    display: flex;
    align-items: center;
    gap: 8px;
    padding-top: 8px;
    border-top: 1px solid var(--outline-variant);
  }  .me-name {
    flex: 1;
    font-size: 13px;
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    text-align: left;
    padding: 4px 6px;
    border-radius: 8px;
    min-width: 0;
  }
  .me-name:hover {
    background: var(--panel-hover);
  }
  /* блок с ником и статусом: два ряда, чтобы статус не лез в кнопку настроек */
  .me-box {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  .me-status {
    width: 100%;
    background: transparent;
    border: none;
    outline: none;
    padding: 2px 6px;
    border-radius: 8px;
    font: inherit;
    font-size: 11.5px;
    color: var(--muted);
    text-overflow: ellipsis;
  }
  .me-status::placeholder {
    color: var(--outline);
  }
  .me-status:hover {
    background: var(--panel-hover);
  }
  .me-status:focus {
    background: var(--surface);
    color: var(--text1);
  }

  /* ---------- чат ---------- */
  .chat {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    background: var(--chat-bg);
  }
  .chat-head {
    flex: none;
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 16px;
    background: var(--bar-bg);
    border-bottom: 1px solid var(--hairline);
  }
  .chat-title {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
  }
  .head-actions {
    margin-left: auto;
    display: flex;
    gap: 6px;
  }
  .head-btn {
    width: 32px;
    height: 32px;
    border-radius: 999px;
    color: var(--muted);
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
  .head-btn:hover {
    background: var(--panel-hover);
    color: var(--text1);
  }
  .head-btn.active {
    background: var(--ok);
    color: #000;
  }
  .online-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--outline);
    flex: none;
  }
  .online-dot.on {
    background: var(--ok);
  }
  .chan-chip {
    width: 26px;
    height: 26px;
    border: 1.5px solid var(--bubble-border);
    border-radius: 4px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
    color: var(--bubble-text);
  }
  .title-text {
    font-size: 16px;
    font-weight: 600;
  }
  .title-box {
    display: flex;
    flex-direction: column;
    min-width: 0;
    line-height: 1.25;
  }
  .title-status {
    font-size: 12.5px;
    color: var(--muted);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 420px;
  }
  .note-bar {
    margin: 8px 16px 0;
    padding: 8px 12px;
    border-radius: 12px;
    font-size: 13px;
    background: color-mix(in srgb, var(--ok) 14%, transparent);
    color: var(--ok);
  }
  .msgs {
    flex: 1;
    overflow-y: auto;
    padding: 16px 20px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .placeholder {
    margin: 40px auto;
    color: var(--muted);
    font-size: 14px;
  }
  .msg {
    max-width: 78%;
    display: flex;
    /* чужие — слева, свои — справа. Явно, а не через дефолт align-items:
       иначе смена выравнивания у .msgs тихо съела бы раскладку. */
    align-self: flex-start;
  }
  .msg.mine {
    align-self: flex-end;
  }
  .msg-body {
    background: var(--bubble-bg);
    border: 1.5px solid var(--bubble-border);
    border-radius: 16px;
    padding: 7px 13px 8px;
    color: var(--bubble-text);
    min-width: 0;
  }
  .msg.mine .msg-body {
    background: var(--bubble-mine-bg);
    border-color: var(--bubble-mine-border);
  }
  .msg-head {
    display: flex;
    align-items: baseline;
    gap: 8px;
    margin-bottom: 2px;
  }
  .msg-name {
    font-size: 12.5px;
    font-weight: 700;
  }
  .msg-time {
    font-size: 11px;
    color: var(--muted);
    margin-left: auto;
  }
  .msg-text {
    font-size: 14.5px;
    line-height: 1.45;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .composer {
    flex: none;
    padding: 4px 20px 12px;
    display: flex;
    align-items: flex-end;
    gap: 8px;
  }
  /* скрепка: input скрыт, клик по label открывает нативный диалог */
  .clip {
    position: relative;
    width: 34px;
    height: 34px;
    flex: none;
    margin-bottom: 4px;
    border-radius: 999px;
    color: var(--muted);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
  }
  .clip:hover {
    background: var(--panel-hover);
    color: var(--text1);
  }
  .clip.disabled {
    opacity: 0.35;
    cursor: default;
  }
  .clip input {
    position: absolute;
    inset: 0;
    opacity: 0;
    cursor: pointer;
  }
  .clip-spin {
    position: absolute;
    right: 2px;
    bottom: 2px;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    border: 2px solid var(--primary);
    border-top-color: transparent;
    animation: spin 0.7s linear infinite;
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
  .composer-input {
    width: 100%;
    background: transparent;
    border: none;
    outline: none;
    resize: none;
    color: var(--bubble-text);
    font: inherit;
    font-size: 15px;
    line-height: 1.5;
    padding: 8px 2px;
    max-height: 150px;
    overflow-y: auto;
  }
  .composer-input::placeholder {
    color: #6f6f6f;
  }
  .composer-input:disabled {
    opacity: 0.5;
  }
</style>
