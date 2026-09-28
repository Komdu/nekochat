// Точка входа: монтируем Svelte-приложение и подключаем общие стили.

import { mount } from "svelte";
import "./app.css";
import App from "./App.svelte";
import { registerSW } from "./lib/registerSW";

const root = document.getElementById("app");
if (root) mount(App, { target: root });

// PWA: регистрация последней, чтобы не задерживать первую отрисовку
registerSW();
