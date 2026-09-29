// Точка входа: монтируем Svelte-приложение и подключаем общие стили.

import { mount } from "svelte";
import "./app.css";
import App from "./App.svelte";
import { registerSW } from "./lib/registerSW";
import { buildMicWorkletSource } from "./lib/calls";
import { createSpeexNode, loadSpeexWasm, wasmUrl } from "./lib/ns";
import { store } from "./lib/store.svelte";

const root = document.getElementById("app");
if (root) mount(App, { target: root });

// PWA: регистрация последней, чтобы не задерживать первую отрисовку
registerSW();

// Хуки для тестов (только dev-сборка):
//  - исходник воркера микрофона, чтобы поднять AudioWorklet с РОВНО этим кодом
//    и проверить размер кадра; копия кода в тесте рано или поздно разошлась бы;
//  - функции шумоподавления, чтобы тест положил настоящий фильтр в настоящий
//    аудио-граф и убедился, что он режет шум.
// Копировать реализацию в тест нельзя — тест врал бы.
if (import.meta.env.DEV) {
  const w = window as unknown as Record<string, unknown>;
  w.__nkoMicSrc = buildMicWorkletSource();
  w.__nkoSpeexWasm = wasmUrl();
  w.__nkoNs = { loadSpeexWasm, createSpeexNode };
  w.__nkoStore = store;
  w.__nkoApi = store.api;
  // подтягиваем wasm заранее: тест и первый звонок не ждут друг друга
  void loadSpeexWasm();
}
