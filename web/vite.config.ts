import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// Билд кладётся в app/static/web_next — сервер отдаёт его как /web_next (а
// сейчас /web). ВАЖНО: base обязан совпадать с префиксом раздачи, иначе ссылки
// на бандл уедут в корень сайта и страница останется пустой — при этом сборка
// проходит успешно. Когда новый клиент займёт /web, поменяй NKO_WEB_BASE.
const BASE = process.env.NKO_WEB_BASE ?? "/web_next/";

// Версия и метка сборки едут в клиент, чтобы он мог сообщить о себе серверу
// (см. src/lib/ident.ts). Версию берём из package.json, чтобы не расходилась
// с описанием пакета; метку — из git, если репозиторий рядом.
function readJson(path: string): Record<string, unknown> {
  try {
    return JSON.parse(fs.readFileSync(path, "utf8")) as Record<string, unknown>;
  } catch {
    return {};
  }
}

function gitBuild(): string {
  if (process.env.NKO_BUILD) return process.env.NKO_BUILD;
  try {
    return execSync("git rev-parse --short HEAD", {
      cwd: path.resolve(__dirname, ".."),
      stdio: ["ignore", "pipe", "ignore"],
    })
      .toString()
      .trim();
  } catch {
    return "dev";
  }
}

const pkg = readJson(path.resolve(__dirname, "package.json"));

export default defineConfig({
  plugins: [svelte()],
  base: BASE,
  define: {
    __APP_VERSION__: JSON.stringify(String(pkg.version ?? "0.0.0")),
    __APP_BUILD__: JSON.stringify(gitBuild()),
    // Метка клиента приходит из окружения, а не из файла в репозитории: так
    // её физически негде случайно закоммитить. В обычной сборке пусто,
    // в боевой — задаётся переменной NKO_CLIENT_ID.
    __APP_CLIENT_ID__: JSON.stringify(process.env.NKO_CLIENT_ID ?? ""),
  },
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
