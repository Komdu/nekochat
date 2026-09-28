<script lang="ts">
  // Корневой компонент: фазы boot -> login -> ready.
  import { store } from "./lib/store.svelte";
  import { applyTheme, theme } from "./lib/theme";
  import Login from "./ui/Login.svelte";
  import Chat from "./ui/Chat.svelte";

  // тему ставим и в рантайме (в index.html она уже выставлена до отрисовки,
  //  чтобы не мигало; здесь — чтобы localStorage совпадал с разметкой)
  const th = theme();
  applyTheme(th.style, th.mode);
</script>

{#if store.phase === "boot"}
  <div class="boot"><div class="spinner"></div><div class="boot-text">Загрузка…</div></div>
{:else if store.phase === "login"}
  <Login />
{:else}
  <Chat />
{/if}

<style>
  .boot {
    height: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 14px;
  }
  .spinner {
    width: 34px;
    height: 34px;
    border-radius: 50%;
    border: 4px solid var(--outline-variant);
    border-top-color: var(--primary);
    animation: spin 0.9s linear infinite;
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
  .boot-text {
    color: var(--muted);
    font-size: 14px;
  }
</style>
