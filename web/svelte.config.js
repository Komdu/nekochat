import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

/** Svelte 5 + TypeScript. Настройки минимальные: препроцессор нужен только
 *  для `lang="ts"`, компилятор и так в runes-режиме. */
export default {
  preprocess: vitePreprocess(),
  compilerOptions: {
    runes: true,
  },
};
