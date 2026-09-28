<script lang="ts">
  // Настройки: тема оформления и профиль.
  //
  // OLED — основная тема, поэтому стоит первой и по умолчанию. Выбор пишется
  // в localStorage (nk_theme) и ставится на <html> как data-theme/data-mode,
  // поэтому применяется мгновенно и переживает перезагрузку.
  import { store } from "../lib/store.svelte";
  import { applyTheme, theme, type ThemeMode, type ThemeStyle } from "../lib/theme";
  import { nsEnabled, setNsEnabled } from "../lib/ns";
  import Dialog from "./Dialog.svelte";
  import Avatar from "./Avatar.svelte";

  let { open = $bindable(false) }: { open?: boolean } = $props();

  const STYLES: Array<{ id: ThemeStyle; name: string; hint: string }> = [
    { id: "oled", name: "OLED", hint: "чистый чёрный, экономит батарею" },
    { id: "material", name: "Material You", hint: "скруглённое, цветное" },
    { id: "win98", name: "Win98", hint: "классические рамки" },
  ];

  let cur = $state<{ style: ThemeStyle; mode: ThemeMode }>(theme());
  let nsOn = $state(nsEnabled());

  function pick(style: ThemeStyle) {
    cur = { style, mode: cur.mode };
    applyTheme(cur.style, cur.mode);
  }

  function setMode(mode: ThemeMode) {
    cur = { style: cur.style, mode };
    applyTheme(cur.style, cur.mode);
  }

  // --- профиль ---
  let bio = $state(store.me?.bio ?? "");
  let status = $state(store.me?.status ?? "");
  let color = $state(store.me?.profile_color ?? "");
  let saving = $state(false);

  async function saveProfile() {
    saving = true;
    try {
      await store.updateProfile({
        bio: bio.trim(),
        status: status.trim(),
        profile_color: color.trim() || undefined,
      });
      store.noteMsg("Профиль сохранён");
      open = false;
    } catch (e) {
      store.noteMsg(e instanceof Error ? e.message : String(e));
    } finally {
      saving = false;
    }
  }

  const SWATCHES = ["#e91e63", "#9c27b0", "#3f51b5", "#2196f3", "#009688", "#ff9800", "#f44336", "#4caf50"];
</script>

<Dialog bind:open title="Настройки">
  <div class="sec">
    <div class="sec-title">Оформление</div>
    <div class="themes">
      {#each STYLES as t (t.id)}
        <button
          class="theme"
          class:on={cur.style === t.id}
          onclick={() => pick(t.id)}
          title={t.hint}
        >
          <span class="theme-swatch sw-{t.id}"></span>
          <span class="theme-name">{t.name}</span>
          <span class="theme-hint">{t.hint}</span>
        </button>
      {/each}
    </div>
    <div class="modes">
      <button class="mode" class:on={cur.mode === "dark"} onclick={() => setMode("dark")}>Тёмная</button>
      <button class="mode" class:on={cur.mode === "light"} onclick={() => setMode("light")}>Светлая</button>
    </div>
    {#if cur.style === "oled"}
      <p class="note">У OLED светлая тема недоступна: чёрный — это суть темы.</p>
    {/if}
  </div>

  <div class="sec">
    <div class="sec-title">Микрофон</div>
    <div class="row">
      <div class="row-info">
        <div class="row-name">Шумоподавление</div>
        <div class="row-hint">
          В Chrome и Edge это RNNoise из WebRTC — фильтр применяется браузером
          к потоку микрофона. AEC и автоусиление оставлены выключенными.
        </div>
      </div>
      <button
        class="mode"
        class:on={nsOn}
        onclick={() => {
          nsOn = !nsOn;
          setNsEnabled(nsOn);
          store.calls?.setNoiseSuppression(nsOn);
        }}
      >{nsOn ? "Вкл" : "Выкл"}</button>
    </div>
    {#if nsOn && store.calls?.noiseSuppression.err}
      <p class="note warn">{store.calls.noiseSuppression.err}</p>
    {/if}
  </div>

  <div class="sec">
    <div class="sec-title">Профиль</div>
    <div class="me-row">
      <Avatar user={store.me} size={44} base={store.base} />
      <div class="me-names">
        <div class="me-display">{store.me?.display_name || store.me?.username}</div>
        <div class="me-user">@{store.me?.username}</div>
      </div>
    </div>
    <label class="field">
      <span>Статус</span>
      <input bind:value={status} maxlength="80" placeholder="чем занят" />
    </label>
    <label class="field">
      <span>О себе</span>
      <textarea bind:value={bio} rows="2" maxlength="300" placeholder="пара слов"></textarea>
    </label>
    <div class="field">
      <span>Цвет профиля</span>
      <div class="swatches">
        {#each SWATCHES as c (c)}
          <button
            class="swatch"
            style={`background:${c}`}
            class:on={color.toLowerCase() === c}
            onclick={() => (color = color.toLowerCase() === c ? "" : c)}
            aria-label="Цвет {c}"
          ></button>
        {/each}
      </div>
    </div>
  </div>

  {#snippet footer()}
    <button class="btn btn-ghost" onclick={() => (open = false)}>Закрыть</button>
    <button class="btn" onclick={saveProfile} disabled={saving}>{saving ? "…" : "Сохранить"}</button>
  {/snippet}
</Dialog>

<style>
  .sec {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .sec-title {
    font-size: 12px;
    font-weight: 700;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.6px;
  }
  .themes {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;
  }
  .theme {
    display: flex;
    flex-direction: column;
    gap: 5px;
    align-items: flex-start;
    padding: 9px;
    border-radius: 12px;
    border: 1.5px solid var(--outline-variant);
    text-align: left;
  }
  .theme:hover {
    background: var(--panel-hover);
  }
  .theme.on {
    border-color: var(--primary);
    background: var(--primary-container);
  }
  .theme-swatch {
    width: 100%;
    height: 30px;
    border-radius: 7px;
    border: 1px solid var(--outline-variant);
  }
  .sw-oled {
    background: #000;
  }
  .sw-material {
    background: linear-gradient(135deg, #6750a4, #eaddff);
  }
  .sw-win98 {
    background: linear-gradient(135deg, #c0c0c0, #ffffc1);
  }
  .theme-name {
    font-size: 12.5px;
    font-weight: 700;
  }
  .theme-hint {
    font-size: 10.5px;
    color: var(--muted);
    line-height: 1.25;
  }
  .modes {
    display: flex;
    gap: 8px;
  }
  .mode {
    padding: 7px 16px;
    border-radius: 999px;
    border: 1.5px solid var(--outline-variant);
    font-size: 13px;
    font-weight: 600;
    color: var(--muted);
  }
  .mode.on {
    border-color: var(--primary);
    background: var(--primary-container);
    color: var(--on-primary-container);
  }
  .note {
    font-size: 12px;
    color: var(--muted);
  }
  .note.warn {
    color: var(--danger);
  }
  .row {
    display: flex;
    align-items: center;
    gap: 14px;
  }
  .row-info {
    flex: 1;
    min-width: 0;
  }
  .row-name {
    font-size: 14px;
    font-weight: 600;
  }
  .row-hint {
    font-size: 12px;
    color: var(--muted);
    line-height: 1.4;
    margin-top: 3px;
  }
  .me-row {
    display: flex;
    align-items: center;
    gap: 11px;
  }
  .me-display {
    font-size: 15px;
    font-weight: 700;
  }
  .me-user {
    font-size: 12px;
    color: var(--muted);
  }
  label.field textarea {
    background: var(--surface);
    color: var(--text1);
    border: 1px solid var(--outline-variant);
    border-radius: 12px;
    padding: 10px 12px;
    outline: none;
    resize: vertical;
    font: inherit;
  }
  label.field textarea:focus {
    border-color: var(--primary);
  }
  .swatches {
    display: flex;
    gap: 7px;
    flex-wrap: wrap;
  }
  .swatch {
    width: 26px;
    height: 26px;
    border-radius: 999px;
    border: 2px solid transparent;
  }
  .swatch.on {
    border-color: var(--text1);
  }
</style>
