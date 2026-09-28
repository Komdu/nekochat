// Точка входа: монтируем Svelte-приложение и подключаем общие стили.

import { mount } from "svelte";
import "./app.css";
import App from "./App.svelte";
import { registerSW } from "./lib/registerSW";
import { buildMicWorkletSource } from "./lib/calls";

const root = document.getElementById("app");
if (root) mount(App, { target: root });

// PWA: регистрация последней, чтобы не задерживать первую отрисовку
registerSW();

// Хук для тестов (только dev-сборка): отдаёт наружу исходник воркера микрофона.
// Тест поднимает AudioWorklet с этим исходником и проверяет, что из него
// выходят кадры ровно по 20 мс. Копировать код в тест нельзя — копия рано или
// поздно разойдётся с настоящим, и тест будет врать.
if (import.meta.env.DEV) {
  (window as unknown as Record<string, unknown>).__nkoMicSrc = buildMicWorkletSource();
}
