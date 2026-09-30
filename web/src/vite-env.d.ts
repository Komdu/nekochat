/// <reference types="svelte" />
/// <reference types="vite/client" />

// Значения, которые подставляет Vite при сборке (см. vite.config.ts).
// Объявлены глобально, чтобы не тащить через каждый импорт.
declare const __APP_VERSION__: string;
declare const __APP_BUILD__: string;
declare const __APP_CLIENT_ID__: string;
