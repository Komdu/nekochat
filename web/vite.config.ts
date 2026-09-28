import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// Билд кладётся в app/static/web_next — сервер отдаёт его как /web_next (а
// сейчас /web). ВАЖНО: base обязан совпадать с префиксом раздачи, иначе ссылки
// на бандл уедут в корень сайта и страница останется пустой — при этом сборка
// проходит успешно. Когда новый клиент займёт /web, поменяй NKO_WEB_BASE.
const BASE = process.env.NKO_WEB_BASE ?? "/web_next/";

export default defineConfig({
  plugins: [svelte()],
  base: BASE,
  build: {
    outDir: "../app/static/web_next",
    emptyOutDir: true,
    target: "es2022",
    assetsDir: "assets",
    sourcemap: false,
  },
  server: {
    port: 5173,
    proxy: {
      // локальная разработка против локального же сервера
      "/api": "http://127.0.0.1:8001",
      "/auth": "http://127.0.0.1:8001",
      "/rooms": "http://127.0.0.1:8001",
      "/users": "http://127.0.0.1:8001",
      "/ws": { target: "ws://127.0.0.1:8001", ws: true },
    },
  },
});
