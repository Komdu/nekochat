<script lang="ts">
  // Логин: вход и регистрация одним экраном, как в десктопе.
  import { store } from "../lib/store.svelte";

  let mode = $state<"login" | "register">("login");
  let username = $state("");
  let password = $state("");
  let display = $state("");

  const busy = $derived(store.busy);
  const err = $derived(store.error);

  async function submit(e: Event) {
    e.preventDefault();
    if (!username.trim() || !password) return;
    try {
      if (mode === "login") await store.login(username.trim(), password);
      else await store.register(username.trim(), password, display.trim() || username.trim());
    } catch {
      /* текст ошибки уже в store.error */
    }
  }
</script>

<div class="login-wrap">
  <form class="login-card" onsubmit={submit}>
    <div class="login-logo">#</div>
    <h1 class="login-title">nekochat</h1>
    <p class="login-sub">{mode === "login" ? "Вход" : "Регистрация"}</p>

    <label class="field">
      <span>Логин</span>
      <!-- svelte-ignore a11y_autofocus -->
      <input bind:value={username} autocomplete="username" autofocus />
    </label>

    <label class="field">
      <span>Пароль</span>
      <input type="password" bind:value={password} autocomplete="current-password" />
    </label>

    {#if mode === "register"}
      <label class="field">
        <span>Имя (как тебя звать)</span>
        <input bind:value={display} autocomplete="nickname" />
      </label>
    {/if}

    {#if err}<div class="login-err">{err}</div>{/if}

    <button class="btn" type="submit" disabled={busy || !username.trim() || !password}>
      {busy ? "…" : mode === "login" ? "Войти" : "Создать аккаунт"}
    </button>

    <button
      class="login-switch"
      type="button"
      onclick={() => {
        mode = mode === "login" ? "register" : "login";
        store.error = "";
      }}
    >
      {mode === "login" ? "Нет аккаунта? Регистрация…" : "Уже есть аккаунт? Войти"}
    </button>
  </form>
</div>

<style>
  .login-wrap {
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 20px;
  }
  .login-card {
    width: 340px;
    max-width: 100%;
    background: var(--panel);
    border: 1px solid var(--outline-variant);
    border-radius: 24px;
    padding: 26px;
    display: flex;
    flex-direction: column;
    gap: 13px;
  }
  .login-logo {
    width: 52px;
    height: 52px;
    border-radius: 18px;
    background: var(--primary);
    color: var(--on-primary);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 24px;
    font-weight: 800;
  }
  .login-title {
    font-size: 24px;
    font-weight: 800;
  }
  .login-sub {
    font-size: 13px;
    color: var(--muted);
    margin-top: -8px;
  }
  .login-err {
    background: color-mix(in srgb, var(--danger) 16%, transparent);
    color: var(--danger);
    border-radius: 12px;
    padding: 9px 12px;
    font-size: 13px;
  }
  .login-switch {
    align-self: center;
    font-size: 13px;
    color: var(--muted);
  }
  .login-switch:hover {
    color: var(--text1);
  }
</style>
