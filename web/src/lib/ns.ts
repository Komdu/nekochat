// Шумоподавление микрофона.
//
// Почему встроенный фильтр браузера, а не отдельная библиотека.
//
// В Chrome и Edge шумоподавление из getUserMedia — это RNNoise из WebRTC APM
// (Audio Processing Module), то есть ровно та же нейросеть, что стоит в
// настольных приложениях. Разница в том, что браузер применяет её сам, до того
// как отдать нам PCM.
//
// Почему не wasm-библиотека: её пришлось бы собирать самой (rnnoise +
// emscripten), потому что готовые npm-пакеты не везут модель. Проверено на
// @jitsi/rnnoise-wasm и @sapphi-red/web-noise-suppressor: без модели
// rnnoise_create отдаёт состояние с нулевыми весами, process_frame ничего не
// делает и возвращает 0 — на синтезированной речи выход равен входу. Мёртвый
// код в клиенте хуже отсутствия кода.
//
// Чего встроенный фильтр не умеет: он молча игнорирует запрос, если браузер
// решит иначе. Поэтому grabMic() проверяет, что ограничение реально применилось,
// и записывает это в состояние звонка — видно в диагностике.

const LS_NS = "nk_nsuppress";

/** Включён ли шумодав. По умолчанию да: в голосовом чате он нужен почти всегда. */
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

/** Ограничения для getUserMedia.
 *
 * AEC (эхо) и AGC (автоусиление) оставлены выключенными намеренно: в десктопе
 * на WebView2 они давали deadlock аудио-графа при одновременном входе и выходе,
 * и AGC в чате ещё и «дышит» громкостью. Шумодав такого не вызывает — это
 * проходной фильтр, а не перестройка графа.
 */
export function micConstraints(ns: boolean): MediaTrackConstraints {
  return {
    echoCancellation: false,
    noiseSuppression: ns,
    autoGainControl: false,
    channelCount: 1,
  };
}
