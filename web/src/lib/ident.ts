// Идентификация клиента: имя, версия, ОС, метка сборки.
//
// Заголовок собирается в одном месте, и всё, что едет наружу, видно здесь.
//
// О значении client_id. Оно приходит из переменной окружения при сборке
// (NKO_CLIENT_ID) и в исходниках не лежит — коммитить нечего. Но подчеркну
// честно: это НЕ секрет и им не защита. Клиент — это JavaScript, который
// браузер отдаёт любому посетителю; что в нём зашито, видно через View Source.
// Значение помогает отличить «свой клиент» от чужого скрипта и поймать
// расхождение сборок, но от того, кто полез читать исходники намеренно,
// оно не защищает. Если нужна настоящая защита — это серверный токен на
// устройстве, а не строка в коде клиента.
//
// WebSocket из браузера не умеет заголовки (new WebSocket(url) не даёт их
// задать), поэтому для сокетов то же значение едет параметром `c=` в URL —
// это ограничение браузера, а не наша прихоть.

export const CLIENT_NAME = "nekochat-web";

/** Имя заголовка — обязано совпадать с client_header_name на сервере. */
export const CLIENT_HEADER = "X-Neko-Client";

/** Метка из окружения сборки; пусто в обычной сборке. */
export const CLIENT_ID = __APP_CLIENT_ID__;
export const CLIENT_OS = detectOS();

/** Версия из package.json, чтоб не расходилась вручную. */
export const CLIENT_VERSION = __APP_VERSION__;

/**
 * Метка сборки. Без неё две сборки одной версии неразличимы, а различать
 * нужно: именно на этом ловится «у тебя старая версия».
 * Прокидывается Vite из переменной окружения при сборке.
 */
export const CLIENT_BUILD = __APP_BUILD__ || "dev";

function detectOS(): string {
  const nav = navigator as Navigator & {
    userAgentData?: { platform?: string };
  };
  if (nav.userAgentData?.platform) return nav.userAgentData.platform.toLowerCase();
  const ua = navigator.userAgent;
  if (/Windows/i.test(ua)) return "windows";
  if (/Android/i.test(ua)) return "android";
  if (/(iPhone|iPad|iPod)/i.test(ua)) return "ios";
  if (/Mac OS X|Macintosh/i.test(ua)) return "macos";
  if (/Linux/i.test(ua)) return "linux";
  return "unknown";
}

function detectEngine(): string {
  const ua = navigator.userAgent;
  if (/Edg\//.test(ua)) return "edge";
  if (/OPR\//.test(ua)) return "opera";
  if (/Firefox\//.test(ua)) return "firefox";
  if (/Chrome\//.test(ua)) return "chromium";
  if (/Safari\//.test(ua)) return "safari";
  return "";
}

/** Значение заголовка: имя/версия (ос; движок) build=метка client=id */
export function clientHeaderValue(): string {
  const engine = detectEngine();
  let v = `${CLIENT_NAME}/${CLIENT_VERSION} (${CLIENT_OS}${engine ? "; " + engine : ""}) build=${CLIENT_BUILD}`;
  if (CLIENT_ID) v += ` client=${CLIENT_ID}`;
  return v;
}

/** Тот же набор, но параметром URL — для WebSocket. */
export function clientQueryValue(): string {
  return encodeURIComponent(clientHeaderValue());
}
