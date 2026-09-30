// Передача файлов: свой бинарный протокол поверх /ws/transfer.
//
// Ключевое решение: сервер работает БАЙТ-В-БАЙТ. Он не знает, что внутри
// кадра, и ничего не разбирает — только релеит. Поэтому метаданные (имя,
// размер, тип) едут в начале первого кадра, а дальше идут сырые байты.
// Благодаря этому сервер не пришлось менять ни строчкой: квоты, приоритеты и
// разрыв сокета уже были готовы.
//
// Формат файлового кадра (тот же 12-байтовый заголовок, kind=3):
//   ver=1 | kind=3 | flags | target/from | length | payload
//   flags: бит0 — по комнате, бит1 — последний кусок,
//          биты 2..15 — stream_id (14 бит, до 16384 потоков на человека)
//
// Метаданные первого кадра:
//   [4 байта длины JSON, little-endian][JSON UTF-8][остальное — начало файла]
//
// Чего здесь нет и почему это нормально:
//  - докачки с середины. Сокет может разорваться посреди файла; тогда передача
//    отменяется, получатель видит «обрыв», отправитель жмёт «отправить снова».
//    Возобновление потребовало бы хранить у отправителя уже принятые куски.
//  - подтверждений по каждому куску. Один ack на последний кусок: он и
//    подтверждает, и заодно проверяет, что получатель вообще жив.
//  - шифрования. Сервер видит только кадры и релеит их; содержимое файла через
//    него проходит, но это отдельный вопрос, и здесь не решён.

const LS_KEY = "nk_last_chat";

/** Размер куска. 64 КБ — компромисс: меньше — много мелких кадров и накладных
 *  расходов на заголовок, больше — при отбрасывании в очереди теряется больше. */
export const CHUNK = 64 * 1024;

/** Файл живёт 5 минут, потом отправка обрывается сама. */
export const TRANSFER_TTL_MS = 5 * 60 * 1000;

/**
 * Потолок на размер файла — 512 МБ.
 *
 * Явного лимита раньше не было нигде: ни клиент, ни сервер не проверяли
 * общий объём, единственным ограничением был таймер. На практике за 5 минут
 * по туннелю уходит сотня мегабайт, так что 512 МБ — это потолок запаса, а
 * не рабочее число. Ставится именно с той стороны, где память: получатель
 * держит все куски до сборки блоба, и больше никакого потолка не было.
 */
export const MAX_FILE = 512 * 1024 * 1024;

const FLAG_ROOM = 1 << 0;
const FLAG_LAST = 1 << 1;
const STREAM_MASK = 0x3fff;
const STREAM_SHIFT = 2;

/** Квитанция получателя: отправленному файлу приходит такой ответ. */
const ACK_HEAD = new Uint8Array([0x41]); // 'A'

export type TransferDir = "out" | "in";
export type TransferState = "sending" | "receiving" | "done" | "error" | "canceled";

export interface Transfer {
  key: string;
  dir: TransferDir;
  stream: number;
  name: string;
  size: number;
  mime: string;
  state: TransferState;
  /** 0..1 */
  progress: number;
  /** с кем или в какой комнате */
  peerId?: number;
  roomId?: number;
  peerName?: string;
  error?: string;
  url?: string;
  startedAt: number;
}

function fmtSize(n: number): string {
  if (n < 1024) return `${n} Б`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} КБ`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} МБ`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} ГБ`;
}

export function humanSize(n: number): string {
  return fmtSize(n);
}

interface Meta {
  n: string;
  s: number;
  t: string;
}

function buildFirstPayload(meta: Meta, head: Uint8Array): Uint8Array {
  const json = new TextEncoder().encode(JSON.stringify(meta));
  const out = new Uint8Array(4 + json.length + head.length);
  new DataView(out.buffer).setUint32(0, json.length, true);
  out.set(json, 4);
  out.set(head, 4 + json.length);
  return out;
}

function parseFirstPayload(p: Uint8Array): { meta: Meta; head: Uint8Array } | null {
  if (p.length < 4) return null;
  const len = new DataView(p.buffer, p.byteOffset, p.byteLength).getUint32(0, true);
  if (len < 4 || len > 4096 || p.length < 4 + len) return null;
  try {
    const json = new TextDecoder().decode(p.subarray(4, 4 + len));
    const meta = JSON.parse(json) as Meta;
    if (typeof meta.n !== "string" || typeof meta.s !== "number") return null;
    return { meta, head: p.subarray(4 + len) };
  } catch {
    return null;
  }
}

/** Менеджер передач. Один на сессию. */
export class FileManager {
  /** Ключ потока: senderId — направление — streamId. */
  private incoming = new Map<string, { meta: Meta; parts: Uint8Array[]; got: number; peerId: number }>();
  private outStream = 0;

  /** Отправить файл. onChange дёргается при каждом изменении. */
  async send(
    file: File,
    target: { peerId?: number; roomId?: number; peerName?: string },
    canSend: (flags: number, target: number, payload: Uint8Array) => boolean,
    onChange: (t: Transfer) => void,
    onDone: (t: Transfer) => void,
    /** Готов ли канал. Опрос вместо одноразовой проверки: сокет передач
     *  открывается при входе и может быть ещё в CONNECTING, когда пользователь
     *  уже прикрепил файл. Одноразовая проверка давала «канал не готов» на
     *  живом сокете. */
    ready: () => boolean = () => true,
    open: () => void = () => {},
  ): Promise<Transfer> {
    const stream = 1 + Math.floor(Math.random() * STREAM_MASK);
    const t: Transfer = {
      key: `out-${target.peerId ?? target.roomId ?? 0}-${stream}`,
      dir: "out",
      stream,
      name: file.name || "файл",
      size: file.size,
      mime: file.type || "application/octet-stream",
      state: "sending",
      progress: 0,
      peerId: target.peerId,
      roomId: target.roomId,
      peerName: target.peerName,
      startedAt: Date.now(),
    };

    const flagsBase = (target.roomId ? FLAG_ROOM : 0) | (stream << STREAM_SHIFT);

    // Размер проверяем ДО гонки: бессмысленно пять минут резать файл, который
    // всё равно не влезет. И заодно предупреждаем, если он заведомо не
    // пройдёт за отведённое время.
    if (file.size > MAX_FILE) {
      t.state = "error";
      t.error = `файл ${fmtSize(file.size)} больше предела ${fmtSize(MAX_FILE)}`;
      onChange(t);
      onDone(t);
      return t;
    }

    // Ждём канал: поднимаем, если закрыт, и даём ему до 3 с на CONNECTING.
    if (!(await this.waitChannel(ready, open, 3000))) {
      t.state = "error";
      t.error = "канал передачи не открылся — проверь интернет и попробуй снова";
      onChange(t);
      onDone(t);
      return t;
    }

    let offset = 0;
    let first = true;
    let canceled = false;
    const timer = window.setTimeout(() => {
      if (!canceled && offset < file.size) {
        canceled = true;
        t.state = "canceled";
        t.error = "время вышло (5 минут)";
        onChange(t);
      }
    }, TRANSFER_TTL_MS);

    try {
      while (offset < file.size) {
        if (canceled) break;
        const end = Math.min(offset + CHUNK, file.size);
        const slice = new Uint8Array(await file.slice(offset, end).arrayBuffer());
        offset = end;
        const last = offset >= file.size;
        const payload = first ? buildFirstPayload({ n: t.name, s: t.size, t: t.mime }, slice) : slice;
        if (!canSend(flagsBase | (last ? FLAG_LAST : 0), this.addr(target), payload)) {
          t.state = "error";
          t.error = "соединение прервалось";
          // Слот на сервере держится до флага last. Без этого пустого кадра
          // следующая передача была бы заблокирована до переподключения.
          this.releaseSlot(flagsBase, this.addr(target), canSend);
          break;
        }
        first = false;
        t.progress = offset / file.size;
        onChange(t);
        // уступаем поток: файлы не должны мешать интерфейсу и голосовым кадрам
        await new Promise((r) => setTimeout(r, 0));
      }
      if (!canceled && t.state === "sending") {
        // ждём квитанцию; без неё помечаем как «не подтверждено»
        const ok = await this.waitAck(stream, 6000);
        t.state = "done";
        if (!ok) t.error = "получатель не подтвердил — возможно, он вышел";
        onChange(t);
        onDone(t);
      }
    } catch (e) {
      t.state = "error";
      t.error = e instanceof Error ? e.message : String(e);
      onChange(t);
      onDone(t);
    } finally {
      window.clearTimeout(timer);
    }
    return t;
  }

  private addr(t: { peerId?: number; roomId?: number }): number {
    return t.roomId ? (t.roomId as number) : (t.peerId as number);
  }

  /** Дождаться готовности канала. Пытаемся открыть и опрашиваем. */
  private async waitChannel(
    ready: () => boolean,
    open: () => void,
    timeout: number,
  ): Promise<boolean> {
    if (ready()) return true;
    open();
    const until = Date.now() + timeout;
    while (Date.now() < until) {
      if (ready()) return true;
      await new Promise((r) => setTimeout(r, 120));
    }
    return ready();
  }

  /** Отпустить занятый слот передачи: пустой последний кадр с тем же stream_id. */
  private releaseSlot(
    flagsBase: number,
    target: number,
    canSend: (flags: number, target: number, payload: Uint8Array) => boolean,
  ): void {
    try {
      canSend(flagsBase | FLAG_LAST, target, new Uint8Array(0));
    } catch {
      /* сокет мёртв — слот снимется при разрыве */
    }
  }

  private acks = new Set<number>();
  private waiters = new Map<number, (ok: boolean) => void>();

  private waitAck(stream: number, timeout: number): Promise<boolean> {
    if (this.acks.has(stream)) {
      this.acks.delete(stream);
      return Promise.resolve(true);
    }
    return new Promise((resolve) => {
      const done = (ok: boolean) => {
        this.waiters.delete(stream);
        resolve(ok);
      };
      this.waiters.set(stream, done);
      window.setTimeout(() => {
        if (this.waiters.get(stream) === done) done(false);
      }, timeout);
    });
  }

  /**
   * Кадр с сервера. Звук и видео сюда не попадают — их разбирает движок звонков.
   * Возвращает готовый список файлов для интерфейса.
   */
  async onFrame(
    flags: number,
    from: number,
    payload: Uint8Array,
    onNew: (t: Transfer) => void,
  ): Promise<void> {
    const stream = (flags >> STREAM_SHIFT) & STREAM_MASK;
    const last = !!(flags & FLAG_LAST);

    // квитанция от получателя: кадр из одного байта 'A'
    if (payload.length === 1 && payload[0] === ACK_HEAD[0]) {
      const w = this.waiters.get(stream);
      if (w) w(true);
      else this.acks.add(stream);
      return;
    }

    const key = `in-${from}-${stream}`;
    let rec = this.incoming.get(key);

    if (!rec) {
      const parsed = parseFirstPayload(payload);
      if (!parsed) return; // битый кадр — молча, иначе разорвём поток
      // Потолок на объявленный размер. Без него отправитель, объявивший
      // 10 байт, мог лить бы в нашу память, пока не кончится браузер:
      // куски лежат в массиве до момента сборки блоба.
      if (parsed.meta.s > MAX_FILE) {
        onNew({
          key, dir: "in", stream,
          name: parsed.meta.n, size: parsed.meta.s, mime: parsed.meta.t,
          state: "error",
          error: `файл больше ${humanSize(MAX_FILE)} — не беру`,
          progress: 0, peerId: from, startedAt: Date.now(),
        });
        return;
      }
      rec = { meta: parsed.meta, parts: [], got: 0, peerId: from };
      this.incoming.set(key, rec);
      if (parsed.head.length) {
        rec.parts.push(parsed.head.slice());
        rec.got += parsed.head.length;
      }
      onNew({
        key,
        dir: "in",
        stream,
        name: rec.meta.n,
        size: rec.meta.s,
        mime: rec.meta.t,
        state: "receiving",
        progress: rec.meta.s ? rec.got / rec.meta.s : 0,
        peerId: from,
        startedAt: Date.now(),
      });
    } else {
      // Принято не должно превышать объявленное: иначе отправитель может
      // лить бесконечно, а таймер на его стороне нас не защищает. Превышение
      // — обрыв с освобождением памяти, а не «продолжим как есть».
      if (rec.got + payload.length > rec.meta.s) {
        this.incoming.delete(key);
        onNew({
          key, dir: "in", stream,
          name: rec.meta.n, size: rec.meta.s, mime: rec.meta.t,
          state: "error",
          error: "пришло больше байт, чем объявлено — передача прервана",
          progress: 0, peerId: from, startedAt: Date.now(),
        });
        return;
      }
      rec.parts.push(payload.slice());
      rec.got += payload.length;
    }

    if (!last) return;

    // последний кусок: собираем файл
    this.incoming.delete(key);
    const blob = new Blob(rec.parts as BlobPart[], { type: rec.meta.t || "application/octet-stream" });
    const url = URL.createObjectURL(blob);
    // квитанция: без неё отправитель не поймёт, дошло ли
    this.sendAck(stream, from);
    onNew({
      key,
      dir: "in",
      stream,
      name: rec.meta.n,
      size: rec.meta.s,
      mime: rec.meta.t,
      state: "done",
      progress: 1,
      peerId: from,
      url,
      startedAt: Date.now(),
    });
    // чистим старые ссылки: иначе блоб держит память до перезагрузки
    window.setTimeout(() => {
      const use = document.querySelector(`a[href="${url}"]`);
      if (!use) URL.revokeObjectURL(url);
    }, 30 * 60 * 1000);
  }

  /** Отправить квитанцию через переданный канал (вне класса: нужен api). */
  onAck: ((flags: number, target: number, payload: Uint8Array) => void) | null = null;

  private sendAck(stream: number, to: number): void {
    const cb = this.onAck;
    if (!cb) return;
    cb(FLAG_LAST | (stream << STREAM_SHIFT), to, new Uint8Array(ACK_HEAD));
  }

  /** Отправить что угодно (используется для отмены — пустой последний кадр). */
  static flags(stream: number, room: boolean, last: boolean): number {
    return (room ? FLAG_ROOM : 0) | (last ? FLAG_LAST : 0) | (stream << STREAM_SHIFT);
  }
}
