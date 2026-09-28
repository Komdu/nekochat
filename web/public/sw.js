// Service worker клиента nekochat.
//
// Задача скромная: дать офлайн-оболочку и быстрый повторный запуск. Поэтому
// стратегии намеренно консервативные:
//
//   навигация      — network-first: свежая страница важнее офлайна, иначе после
//                    деплоя пользователь долго видел бы старый бандл;
//   /assets/*      — cache-first: имена файлов с хешем, они неизменяемы;
//   /api, /ws, ... — мимо кэша полностью: сообщения и токены кэшировать нельзя;
//   значки, шрифты — cache-first, они статичные.
//
// Кэш версионируется через CACHE: при смене имени старый кэш удаляется целиком.

const CACHE = "nekochat-v1";

// Хеши в именах файлов => содержимое неизменяемо, можно брать из кэша.
const IMMUTABLE = /^\/web(_next)?\/assets\//;

// Никогда не кэшируем: живое состояние и секреты.
const NEVER = [
  "/api/",
  "/auth/",
  "/ws",
  "/rooms",
  "/users",
  "/avatars/",
];

self.addEventListener("install", (event) => {
  // Ничего не precache'им: собранный клиент сам подтянет нужное при первом
  // запуске. Пустая установка безопаснее, чем замороженная на минуту версия.
  self.skipWaiting();
  event.waitUntil(Promise.resolve());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys();
      await Promise.all(names.filter((n) => n !== CACHE).map((n) => caches.delete(n)));
      await self.clients.claim();
    })(),
  );
});

function isNever(url) {
  return NEVER.some((p) => url.pathname === p || url.pathname.startsWith(p));
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  // чужойorigin и не-HTTP — не наше дело
  if (url.origin !== self.location.origin) return;
  if (isNever(url)) return;

  // WebSocket через SW не ходит, но проверка дешёвая и снимает вопросы
  if (req.headers.get("upgrade") === "websocket") return;

  // --- навигация: сначала сеть, кэш только как запасной вариант ---
  if (req.mode === "navigate") {
    event.respondWith(
      (async () => {
        try {
          const fresh = await fetch(req);
          const copy = fresh.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
          return fresh;
        } catch {
          const cached = await caches.match(req, { ignoreSearch: true });
          if (cached) return cached;
          // офлайн, а оболочки нет: пусть браузер покажет свою страницу
          return new Response(
            "<!doctype html><meta charset=utf-8><title>nekochat</title>" +
              "<body style='background:#000;color:#f2f2f2;font:16px sans-serif;" +
              "display:flex;align-items:center;justify-content:center;height:100vh;margin:0'>" +
              "nekochat — нет связи</body>",
            { headers: { "Content-Type": "text/html; charset=utf-8" }, status: 200 },
          );
        }
      })(),
    );
    return;
  }

  // --- неизменяемое: сначала кэш ---
  if (IMMUTABLE.test(url.pathname)) {
    event.respondWith(
      (async () => {
        const hit = await caches.match(req);
        if (hit) return hit;
        const fresh = await fetch(req);
        if (fresh.ok) {
          const copy = fresh.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        }
        return fresh;
      })(),
    );
    return;
  }

  // --- остальное (иконки, шрифты, манифест): кэш с фоновым обновлением ---
  event.respondWith(
    (async () => {
      const hit = await caches.match(req);
      const net = fetch(req)
        .then((fresh) => {
          if (fresh.ok) {
            const copy = fresh.clone();
            caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
          }
          return fresh;
        })
        .catch(() => null);
      return hit || (await net) || new Response("", { status: 504 });
    })(),
  );
});

// Сообщение из страницы: сбросить кэш (например, после обновления).
self.addEventListener("message", (event) => {
  if (event.data === "skipWaiting") self.skipWaiting();
  if (event.data === "clearCache") {
    event.waitUntil(caches.keys().then((n) => Promise.all(n.map((x) => caches.delete(x)))));
  }
});
