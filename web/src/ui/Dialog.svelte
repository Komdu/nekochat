<script lang="ts">
  // Модальное окно. Открывается сменой open, закрывается Esc, кликом по
  // подложке и кнопкой. Возвращает фокус на элемент, который его открыл.
  import type { Snippet } from "svelte";

  let {
    open = $bindable(false),
    title,
    children,
    footer,
  }: {
    open?: boolean;
    title: string;
    children: Snippet;
    footer?: Snippet;
  } = $props();

  let opener: HTMLElement | null = null;

  $effect(() => {
    if (open) {
      opener = document.activeElement as HTMLElement | null;
      // фокус внутрь, иначе Esc не доедет до обработчика на document
      queueMicrotask(() => document.querySelector<HTMLElement>(".dlg-card input, .dlg-card textarea, .dlg-card button")?.focus());
    } else if (opener) {
      opener.focus();
      opener = null;
    }
  });

  function close() {
    open = false;
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === "Escape") {
      e.stopPropagation();
      close();
    }
  }
</script>

<svelte:window onkeydown={open ? onKey : undefined} />

{#if open}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="dlg-backdrop" onclick={close}>
    <div
      class="dlg-card"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      tabindex="-1"
      onclick={(e) => e.stopPropagation()}
    >
      <div class="dlg-head">
        <span class="dlg-title">{title}</span>
        <button class="dlg-x" onclick={close} aria-label="Закрыть">✕</button>
      </div>
      <div class="dlg-body">
        {@render children()}
      </div>
      {#if footer}
        <div class="dlg-foot">
          {@render footer()}
        </div>
      {/if}
    </div>
  </div>
{/if}

<style>
  .dlg-backdrop {
    position: fixed;
    inset: 0;
    z-index: 300;
    background: rgba(0, 0, 0, 0.6);
    display: flex;
    align-items: center;
    justify-content: center;
    backdrop-filter: blur(3px);
    padding: 20px;
  }
  .dlg-card {
    width: 400px;
    max-width: 100%;
    max-height: calc(100vh - 40px);
    overflow-y: auto;
    background: var(--panel);
    border: 1px solid var(--outline-variant);
    border-radius: 20px;
    padding: 20px 22px;
    display: flex;
    flex-direction: column;
    gap: 14px;
    box-shadow: 0 24px 70px rgba(0, 0, 0, 0.6);
  }
  .dlg-head {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .dlg-title {
    font-size: 17px;
    font-weight: 700;
    flex: 1;
  }
  .dlg-x {
    width: 30px;
    height: 30px;
    border-radius: 999px;
    color: var(--muted);
    font-size: 13px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
  .dlg-x:hover {
    background: var(--panel-hover);
    color: var(--text1);
  }
  .dlg-body {
    display: flex;
    flex-direction: column;
    gap: 13px;
  }
  .dlg-foot {
    display: flex;
    gap: 10px;
    justify-content: flex-end;
  }
</style>
