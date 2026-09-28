import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// Билд кладётся прямо в app/static/web_next — сервер будет отдавать его
// как /web (см. app/main.py: _static_dir()). Vite-обёртка не нужна: пути
// внутри собранного приложения абсолютные, как и ожидает текущий клиент.
export default defineConfig({
  plugins: [svelte()],
  base: "/",
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
