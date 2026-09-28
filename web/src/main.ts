// Точка входа. Пока — проверочный каркас: убеждаемся, что тулчейн
// Svelte + Vite собирается, и только потом наполняем его частями.

import { mount } from "svelte";
import App from "./App.svelte";

const root = document.getElementById("app");
if (root) mount(App, { target: root });
