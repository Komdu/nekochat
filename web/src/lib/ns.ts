// Шумоподавление микрофона: Speex preprocessor в AudioWorklet.
//
// Почему Speex, а не отдельный RNNoise. Готовые npm-пакеты с RNNoise не везут
// модель нейросети: @jitsi/rnnoise-wasm весит 112 КБ, но самой модели там нет
// (проверено на синтезированной речи — rnnoise_process_frame возвращает 0 и не
// меняет сигнал). Собрать самому значит тащить Docker с emscripten. У Speex
// коэффициенты зашиты в коде: модель не нужна, отдельная сборка не нужна,
// wasm — 55 КБ.
//
// Почему не встроенный шумодав браузера. Он есть (в Chrome и Edge это тот же
// RNNoise из WebRTC APM), но это запасной вариант: он работает через
// getUserMedia и о нём нельзя узнать, применился ли он. Свой Speex мы ставим в
// воркер сами и точно видим, что он стоит в графе.
//
// Про двойную обработку: одновременно Speex и браузерный шумодав включать нельзя
// — два фильтра подряд дают слышимые артефакты. Поэтому выбор делается один раз,
// до getUserMedia (см. nsPlan).
//
// AEC (эхо) и AGC (автоусиление) оставлены выключенными: в десктопе на WebView2
// они давали deadlock аудио-графа, а AGC в чате ещё и «дышит» громкостью.

import { SpeexWorkletNode, loadSpeex } from "@sapphi-red/web-noise-suppressor";
// wasm приходит через собственный экспорт пакета ("./speex.wasm"), а не путём
// в dist/: dist/ внутри node_modules закрыт полем exports
import speexWasmUrl from "@sapphi-red/web-noise-suppressor/speex.wasm?url";
// Модуль процессора для AudioWorklet: его надо добавить в контекст через
// addModule ДО создания узла, конструктор пакета этого не делает.
import speexWorkletUrl from "@sapphi-red/web-noise-suppressor/speexWorklet.js?url";

const LS_NS = "nk_nsuppress";

/** Включён ли шумоподавление. По умолчанию да: в голосовом чате оно нужно. */
export function nsEnabled(): boolean {
  try {
    const v = localStorage.getItem(LS_NS);
    return v === null ? true : v === "1";
  } catch {
    return true;
  }
}

export function setNsEnabled(on: boolean): void {
  try {
    localStorage.setItem(LS_NS, on ? "1" : "0");
  } catch {
    /* приватный режим */
  }
}

let wasmPromise: Promise<ArrayBuffer | null> | null = null;

/** Контексты, куда уже добавлен модуль процессора Speex. */
const addedModules = new WeakSet<AudioContext>();

/** Байты wasm, один раз на страницу. null — не вышло, работаем без Speex. */
export function loadSpeexWasm(): Promise<ArrayBuffer | null> {
  if (!wasmPromise) {
    wasmPromise = loadSpeex({ url: speexWasmUrl }).catch(() => null);
  }
  return wasmPromise;
}

/** Решение, принятое один раз на захват микрофона. */
export type NsPlan =
  | { mode: "speex"; wasm: ArrayBuffer }
  | { mode: "browser" }
  | { mode: "off" };

/**
 * Что делать с шумодавлением. Вызывается до getUserMedia, потому что от ответа
 * зависит, просим ли мы у браузера noiseSuppression: с собственным Speex его
 * просить нельзя — два фильтра подряд.
 */
export async function planNoiseSuppression(on: boolean): Promise<NsPlan> {
  if (!on) return { mode: "off" };
  const wasm = await loadSpeexWasm();
  if (wasm) return { mode: "speex", wasm };
  // Speex не загрузился — лучше встроенный фильтр, чем ничего
  return { mode: "browser" };
}

/** Ограничения микрофона под выбранный план. */
export function micConstraints(plan: NsPlan): MediaTrackConstraints {
  return {
    echoCancellation: false,
    // свой Speex уже фильтрует; иначе просим фильтр у браузера
    noiseSuppression: plan.mode === "browser",
    autoGainControl: false,
    channelCount: 1,
  };
}

/** URL wasm — нужен хукам для тестов, которые поднимают настоящий фильтр
 *  в настоящем графе, а не его копию. */
export function wasmUrl(): string {
  return speexWasmUrl;
}

/** Ставит Speex между источником микрофона и нашим воркером захвата.
 *
 *  Особенность пакета: конструктор SpeexWorkletNode НЕ вызывает addModule за нас
 *  и просто бросает AudioWorkletNode — без предварительно добавленного модуля
 *  браузер падает с «AudioWorklet does not have a valid AudioWorkletGlobalScope».
 *  Поэтому addModule здесь.
 */
export async function createSpeexNode(
  ctx: AudioContext,
  wasm: ArrayBuffer,
): Promise<{ node: AudioNode; destroy: () => void }> {
  // модуль процессора добавляется один раз на контекст
  if (!addedModules.has(ctx)) {
    await ctx.audioWorklet.addModule(speexWorkletUrl);
    addedModules.add(ctx);
  }
  const node = new SpeexWorkletNode(ctx, { maxChannels: 1, wasmBinary: wasm });
  return {
    node,
    destroy: () => {
      try {
        node.destroy();
      } catch {
        /* уже уничтожен */
      }
    },
  };
}
