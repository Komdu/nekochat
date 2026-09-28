<script lang="ts">
  // Создание комнаты и добавление участника — одной формой: поле «имя»
  // и необязательное «пригласить @ник». Так меньше кликов, чем два диалога.
  import { store } from "../lib/store.svelte";
  import Dialog from "./Dialog.svelte";

  let { open = $bindable(false) }: { open?: boolean } = $props();

  let name = $state("");
  let invite = $state("");
  let busy = $state(false);
  let err = $state("");

  $effect(() => {
    if (open) {
      name = "";
      invite = "";
      err = "";
    }
  });

  async function submit(e: Event) {
    e.preventDefault();
    const nm = name.trim();
    if (!nm || busy) return;
    busy = true;
    err = "";
    try {
      const room = await store.api.createRoom(nm);
      // приглашение необязательно: комната уже создана, даже если юзер не найден
      const who = invite.trim().replace(/^@/, "");
      if (who) {
        try {
          await store.api.addMember(room.id, who);
        } catch (e2) {
          store.noteMsg("Комната создана, но пригласить не вышло: " + (e2 instanceof Error ? e2.message : e2));
        }
      }
      await store.reload();
      store.selectRoom(room);
      open = false;
    } catch (e2) {
      err = e2 instanceof Error ? e2.message : String(e2);
    } finally {
      busy = false;
    }
  }
</script>

<Dialog bind:open title="Новая комната">
  <form class="form" onsubmit={submit}>
    <label class="field">
      <span>Название</span>
      <!-- svelte-ignore a11y_autofocus -->
      <input bind:value={name} maxlength="64" placeholder="например, общий чат" autofocus />
    </label>
    <label class="field">
      <span>Пригласить (необязательно)</span>
      <input bind:value={invite} placeholder="ник без @" />
    </label>
    {#if err}<div class="dlg-err">{err}</div>{/if}
  </form>

  {#snippet footer()}
    <button class="btn btn-ghost" onclick={() => (open = false)}>Отмена</button>
    <button class="btn" onclick={submit} disabled={busy || !name.trim()}>
      {busy ? "…" : "Создать"}
    </button>
  {/snippet}
</Dialog>

<style>
  .form {
    display: flex;
    flex-direction: column;
    gap: 13px;
  }
  .dlg-err {
    background: color-mix(in srgb, var(--danger) 16%, transparent);
    color: var(--danger);
    border-radius: 12px;
    padding: 9px 12px;
    font-size: 13px;
  }
</style>
