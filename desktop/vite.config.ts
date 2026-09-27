import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Tauri dev: фронт на http://localhost:1420, API ходит напрямую (CORS на сервере "*").
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});