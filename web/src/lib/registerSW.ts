// Регистрация service worker (PWA).
//
// Отдельный модуль, а не строка в main.ts: регистрация должна быть последней
// и не должна мешать монтированию. В dev-режиме Vite регистрировать нечего —
// путь /sw.js там отдаёт сам Vite, и воркер в обманку попал бы с исходниками.

/** Базовый путь клиента: "/web/" или "/web_next/". Из index.html это не узнать,
 *  поэтому берём из расположения собственного скрипта. */
function swUrl(): string {
  try {
    const here = new URL(import.meta.url);
    // /web/assets/index-xxx.js -> /web/sw.js
    const base = here.pathname.replace(/\/assets\/[^/]+$/, "/");
    return new URL("sw.js", here.origin + base).pathname;
  } catch {
    return "/sw.js";
  }
}

export function registerSW(): void {
  if (!("serviceWorker" in navigator)) return;
  // localhost — безопасный контекст, но в dev-режиме воркер только мешает
  if (import.meta.env.DEV) return;

  const url = swUrl();
  window.addEventListener("load", () => {
    navigator.serviceWorker.register(url).catch(() => {
      // не смогли зарегистрировать — работаем просто без офлайна
    });
  });
}
