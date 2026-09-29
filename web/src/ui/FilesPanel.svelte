<script lang="ts">
  // Панель передач файлов: что отправляется, что пришло, что скачать.
  //
  // Файлы живут 5 минут и лежат у отправителя — сервер только релеит байты и
  // ничего не хранит. Поэтому принятый файл держится в браузере как блоб и
  // живёт до перезагрузки страницы: «сохранить на диск» нужно успеть нажать.
  import { store } from "../lib/store.svelte";
  import { humanSize } from "../lib/files";
  import Icon from "./Icon.svelte";

  const TABS: Array<{ key: "in" | "out" | "all"; name: string }> = [
    { key: "in", name: "Входящие" },
    { key: "out", name: "Отправленные" },
  ];

  let tab = $state<"in" | "out" | "all">("in");

  const shown = $derived(store.transfers.filter((t) => (tab === "all" ? true : t.dir === tab)));
  const hasIn = $derived(store.transfers.some((t) => t.dir === "in"));
  const active = $derived(store.transfers.filter((t) => t.state === "sending" || t.state === "receiving"));

  function who(t: { peerId?: number; peerName?: string }): string {
    if (t.peerName) return t.peerName;
    if (t.peerId != null) {
      const u = store.usersMap[t.peerId];
      return u?.display_name || u?.username || `@${t.peerId}`;
    }
    return "";
  }

  function stateText(t: { state: string; error?: string }): string {
    if (t.error) return t.error;
    switch (t.state) {
      case "sending":
        return "отправляется…";
      case "receiving":
        return "принимается…";
      case "done":
        return "готово";
      case "canceled":
        return "отменено";
      default:
        return "ошибка";
    }
  }
</script>

{#if store.transfers.length > 0}
  <div class="files-panel">
    <div class="files-head">
      <div class="tabs">
        {#each TABS as t (t.key)}
          <button class="tab" class:on={tab === t.key} onclick={() => (tab = t.key)}>
            {t.name}
            {#if t.key === "in" && hasIn}<span class="tab-dot"></span>{/if}
          </button>
        {/each}
      </div>
      {#if active.length > 0}
        <span class="files-active">{active.length} в работе</span>
      {/if}
    </div>

    <div class="files-list">
      {#each shown as t (t.key)}
        <div class="file-row" class:done={t.state === "done"} class:bad={t.state === "error" || t.state === "canceled"}>
          <span class="file-ico"><Icon name={t.dir === "in" ? "arrow" : "mail"} size={15} /></span>
          <div class="file-info">
            <div class="file-name" title={t.name}>{t.name}</div>
            <div class="file-sub">
              {humanSize(t.size)} · {who(t)}
              {#if t.state !== "done" && t.state !== "error" && t.state !== "canceled"}
                — {stateText(t)}
              {/if}
              {#if t.state === "done" && t.dir === "out" && !t.error} — доставлено{/if}
            </div>
            {#if t.state === "sending" || t.state === "receiving"}
              <div class="bar"><div class="bar-fill" style={`width:${Math.round(t.progress * 100)}%`}></div></div>
            {/if}
            {#if t.error}<div class="file-err">{t.error}</div>{/if}
          </div>
          {#if t.state === "done" && t.dir === "in" && t.url}
            <a class="file-dl" href={t.url} download={t.name}>Сохранить</a>
          {/if}
        </div>
      {/each}
      {#if shown.length === 0}
        <div class="files-empty">Пока пусто</div>
      {/if}
    </div>
  </div>
{/if}

<style>
  .files-panel {
    flex: none;
    margin: 0 16px 8px;
    background: var(--panel);
    border: 1px solid var(--outline-variant);
    border-radius: 14px;
    overflow: hidden;
  }
  .files-head {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 7px 10px;
    border-bottom: 1px solid var(--outline-variant);
  }
  .tabs {
    display: flex;
    gap: 4px;
  }
  .tab {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 12px;
    font-weight: 600;
    color: var(--muted);
    padding: 4px 9px;
    border-radius: 999px;
  }
  .tab.on {
    background: var(--primary-container);
    color: var(--on-primary-container);
  }
  .tab-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--ok);
  }
  .files-active {
    margin-left: auto;
    font-size: 11px;
    color: var(--muted);
  }
  .files-list {
    max-height: 170px;
    overflow-y: auto;
    padding: 5px;
  }
  .file-row {
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 6px 7px;
    border-radius: 10px;
  }
  .file-row.done {
    background: color-mix(in srgb, var(--ok) 8%, transparent);
  }
  .file-row.bad {
    background: color-mix(in srgb, var(--danger) 8%, transparent);
  }
  .file-ico {
    color: var(--muted);
    display: inline-flex;
    flex: none;
  }
  .file-info {
    flex: 1;
    min-width: 0;
  }
  .file-name {
    font-size: 13px;
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .file-sub {
    font-size: 11.5px;
    color: var(--muted);
  }
  .file-err {
    font-size: 11.5px;
    color: var(--danger);
  }
  .bar {
    height: 3px;
    border-radius: 2px;
    background: var(--outline-variant);
    margin-top: 4px;
    overflow: hidden;
  }
  .bar-fill {
    height: 100%;
    background: var(--primary);
    transition: width 0.15s;
  }
  .file-dl {
    flex: none;
    font-size: 12px;
    font-weight: 600;
    padding: 5px 11px;
    border-radius: 999px;
    background: var(--primary);
    color: var(--on-primary);
    text-decoration: none;
  }
  .files-empty {
    color: var(--muted);
    font-size: 12.5px;
    text-align: center;
    padding: 14px 8px;
  }
</style>
