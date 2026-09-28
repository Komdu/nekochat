// Точка входа: монтируем Svelte-приложение и подключаем общие стили.

import { mount } from "svelte";
import "./app.css";
import App from "./App.svelte";

const root = document.getElementById("app");
if (root) mount(App, { target: root });
