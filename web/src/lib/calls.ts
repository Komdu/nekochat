// Звонки без WebRTC: аудио идёт Opus'ом по WebSocket, сервер — просто реле
// (call* для сигналинга, call_audio для пересылки Opus-кадров адресату).
// Микрофон → AudioEncoder(opus) → base64 → WS; приём → AudioDecoder → AudioContext.
//
// Два режима:
//  1) 1-к-1 звонок: to_id в сигналинге и аудио (один собеседник, один декодер).
//  2) Голосовой канал комнаты: room_id — сервер релеит всем участникам комнаты,
//     каждый отдаёт свой Opus-поток и микширует N-1 входящих на клиенте
//     (на один общий AudioContext, каждая чужая речь — свой декодер + буфер).

import type { WsEvent } from "./types";
import { MK_AUDIO, MK_VIDEO, MFLAG_ROOM } from "./net";

export type CallPhase = "idle" | "outgoing" | "incoming" | "connecting" | "active" | "ended";

function phaseIs(actual: CallPhase, expected: CallPhase): boolean {
  return actual === expected;
}

export interface CallPeer {
  id: number;
  screen: boolean; // этот участник показывает экран
}

export interface CallState {
  phase: CallPhase;
  peerId: number | null; // 1-1: собеседник
  roomId: number | null; // канал: комната
  inviterId: number | null; // канал: кто позвал (для инвайта)
  startedAt: number | null;
  muted: boolean;
  reason: string;
  screenOn: boolean; // я показываю экран
  screenActive: boolean; // 1-1: мне показывают экран
  screenError: string;
  participants: CallPeer[];
}

/** Один собеседник в активном звонке/канале: декодер + джиттер-буфер + планировщик. */
interface RemotePeer {
  /** счётчик кадров на приёме: в JSON-пути seq ехал в сообщении, в бинарном
   *  фрейме для него нет места — ведём сами, чтобы таймстемп не поехал */
  rxSeq: number;
  decoder: AudioDecoder | null;
  decBuffer: AudioBuffer[];
  nextTime: number | null;
  decIn: number;
  decPlayed: number;
  decFirst: boolean;
}

/** Демонстрация экрана одного из участников: декодер + холст. */
interface RemoteScreen {
  rxSeq: number;
  decoder: VideoDecoder | null;
  canvas: HTMLCanvasElement | null;
}

const RING_TIMEOUT_MS = 45000;
const END_TO_IDLE_MS = 2500;

const SAMPLE_RATE = 48000; // opus
const FRAME_US = 20_000; // 20 мс = 960 сэмплов @48k
const FRAME_SAMPLES = 960;
const PREBUFFER_MS = 400; // стартовый запас воспроизведения на приёме (джиттер-буфер), мс
const START_FRAMES = 16; // не начинаем играть, пока не накопится ~320 мс звука

let callSeq = 0;

// Ловим JS-ошибки/исключения на уровне страницы и докладываем через dbg()
// (diagnose: заморозка main-thread в момент ответа — ошибки редко, но показательно).
const jsErrors: Array<Record<string, unknown>> = [];
window.addEventListener("error", (e) => {
  jsErrors.push({
    at: Date.now(),
    kind: "error",
    msg: String((e && e.message) || e || "unknown"),
    file: (e as any).filename,
    line: (e as any).lineno,
  });
  if (jsErrors.length > 20) jsErrors.shift();
});
window.addEventListener("unhandledrejection", (e) => {
  const r = (e as PromiseRejectionEvent).reason;
  jsErrors.push({
    at: Date.now(),
    kind: "rejection",
    msg: r instanceof Error ? r.message : String(r),
  });
  if (jsErrors.length > 20) jsErrors.shift();
});

function b64encode(bytes: Uint8Array): string {
  let bin = "";
  const step = 0x8000;
  for (let i = 0; i < bytes.length; i += step) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + step) as unknown as number[]);
  }
  return btoa(bin);
}

function b64decode(b64: string): Uint8Array {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export class CallEngine {
  private meId: number;
  private signal: (msg: Record<string, unknown>) => void;

  private peerId: number | null = null;
  private roomId: number | null = null;
  private inviterId: number | null = null;
  private callId: string | null = null;
  private state: CallState = {
    phase: "idle", peerId: null, roomId: null, inviterId: null, startedAt: null,
    muted: false, reason: "", screenOn: false, screenActive: false, screenError: "", participants: [],
  };
  private ringTimer: number | null = null;
  private endTimer: number | null = null;
  private gen = 0;

  // аудио-тулзы
  private stream: MediaStream | null = null;
  private ctx: AudioContext | null = null;
  private script: ScriptProcessorNode | null = null;
  private encoder: AudioEncoder | null = null;
  private encBuffer: Float32Array = new Float32Array(0); // накопление 20мс кадров
  private encTs: number = 0;
  private peers = new Map<number, RemotePeer>(); // собеседники: decoder+буфер на каждого
  // диагностика (временная, для отладки звонков)
  private dbSent = 0;
  private workletNode: AudioWorkletNode | null = null;
  private lastOnProc = 0;
  private watchdog: number | null = null;

  private ctxPlay: AudioContext | null = null;

  /** Состояние WS (для диагностики: readyState при заморозке main-thread). */
  wsStateGetter: () => number = () => -1;

  // демонстрация экрана (видео по WS, без WebRTC): своя (захват+кодирование) и чужие (декодирование)
  private screenStream: MediaStream | null = null;
  private screenTrack: MediaStreamTrack | null = null;
  private screenVideo: HTMLVideoElement | null = null; // скрытый видео-элемент захвата
  private screenProcessor: any = null; // MediaStreamTrackProcessor
  private screenReader: ReadableStreamDefaultReader<VideoFrame> | null = null;
  private screenEncoder: VideoEncoder | null = null;
  private screens = new Map<number, RemoteScreen>(); // чужие демонстрации: from_id → {decoder, canvas}
  private screenSeq = 0;
  private screenBitrate = 1_200_000; // стартовый битрейт видео
  private screenBytes = 0; // отправлено байт в текущем окне адаптации
  private screenAdaptAt = 0; // время начала окна
  private screenFrameAt = 0; // последний закодированный кадр
  private screenForceKey = false; // следующий кадр — ключевой

  onState: (s: CallState) => void = () => {};

  /** Бинарный канал для аудио/видео. null -> работаем по старому JSON-пути.
   *  Стенд ставит store.tsx (api.sendMedia). */
  mediaSink: ((kind: number, flags: number, target: number, payload: Uint8Array) => boolean) | null = null;

  constructor(meId: number, signal: (msg: Record<string, unknown>) => void) {
    this.meId = meId;
    this.signal = signal;
  }

  /** Отправить кадр бинарно. false — сокет не готов: вызывающий решает
   *  (фолбэк на /ws или дроп). */
  private sendMediaFrame(kind: number, payload: Uint8Array): boolean {
    const sink = this.mediaSink;
    if (!sink) return false;
    if (this.roomId != null) return sink(kind, MFLAG_ROOM, this.roomId, payload);
    if (this.peerId != null) return sink(kind, 0, this.peerId, payload);
    return false;
  }

  get current(): CallState {
    return { ...this.state };
  }

  /** Временная телеметрия звонка — сервер логирует в wsDBG и не релеит. */
  private dbg(payload: Record<string, unknown>): void {
    try {
      const extra: Record<string, unknown> = {};
      if (jsErrors.length) extra.jsErr = jsErrors.splice(0);
      this.signal({ type: "dbg", tag: "call", ...extra, ...payload });
    } catch {
      /* noop */
    }
  }

  private emit(): void {
    this.onState({ ...this.state });
  }

  /** Входящий бинарный кадр из /ws/media.
   *
   *  В 4-байтовом слоте кадра сервер кладёт id ОТПРАВИТЕЛЯ (не адресата), так что
   *  собеседник известен всегда — и для 1-1, и для голосового канала. Флаг
   *  MFLAG_ROOM означает только «это broadcast по комнате».
   */
  handleMedia(kind: number, flags: number, from: number, payload: Uint8Array): void {
    if (this.state.phase !== "active" && this.state.phase !== "connecting") return;
    if (this.roomId == null && this.peerId == null) return;
    if (from <= 0 || from === this.meId) return; // эхо себе не играем

    if (kind === MK_AUDIO) {
      this.addParticipant(from); // догоняем участника, чей анонс могли пропустить
      const peer = this.ensurePeer(from);
      if (!peer.decoder || peer.decoder.state !== "configured") return;
      try {
        peer.decoder.decode(
          new EncodedAudioChunk({ type: "key", timestamp: peer.rxSeq++ * FRAME_US, data: payload }),
        );
      } catch {
        /* битый кадр — пропускаем */
      }
      return;
    }

    if (kind === MK_VIDEO) {
      const scr = this.screens.get(from);
      if (!scr || !scr.decoder || scr.decoder.state !== "configured") return;
      if (this.state.phase !== "active") return;
      try {
        scr.decoder.decode(
          new EncodedVideoChunk({ type: "key", timestamp: scr.rxSeq++ * 33_000, data: payload }),
        );
      } catch {
        /* битый кадр */
      }
    }
  }

  private setState(patch: Partial<CallState>): void {
    this.state = { ...this.state, ...patch };
    this.emit();
  }

  private clearRingTimer(): void {
    if (this.ringTimer != null) {
      window.clearTimeout(this.ringTimer);
      this.ringTimer = null;
    }
  }

  private clearEndTimer(): void {
    if (this.endTimer != null) {
      window.clearTimeout(this.endTimer);
      this.endTimer = null;
    }
  }

  private inChannel(): boolean {
    return this.roomId != null;
  }

  // ---------- аудио-пайплайн ----------

  private codecsOk(): boolean {
    return !!(window as any).AudioEncoder && !!(window as any).AudioDecoder;
  }

  /** Захват микрофона: пробуем без AEC/шумодава (Windows/WebView2 с ними возможен
   *  deadlock аудио-графа при одновременном входе и выходе), фолбэк — дефолт. */
  private async grabMic(): Promise<{ stream: MediaStream; cfg: string }> {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
        video: false,
      });
      return { stream, cfg: "aec-off" };
    } catch {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      return { stream, cfg: "default" };
    }
  }

  private async startMicAndEncoder(): Promise<void> {
    if (!this.codecsOk()) throw new Error("no-codecs");
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw new Error("no-media-devices");
    }
    const { stream, cfg } = await this.grabMic();
    this.stream = stream;
    const ctx = new AudioContext({ sampleRate: SAMPLE_RATE });
    await ctx.resume();
    this.ctx = ctx;
    // Воспроизведение входящего голоса — ОТДЕЛЬНЫЙ AudioContext: не делим один аудио-граф
    // между захватом микрофона и рендером (в WebView2 это место deadlock-а).
    let playCtx: AudioContext | null = null;
    try {
      playCtx = new AudioContext({ sampleRate: SAMPLE_RATE });
      await playCtx.resume();
    } catch {
      playCtx = null;
    }
    this.ctxPlay = playCtx ?? ctx;
    this.dbg({ ev: "mic_ok", ctxRate: ctx.sampleRate, ctxBase: ctx.baseLatency ?? 0, micCfg: cfg, playSep: playCtx != null });
    const src = ctx.createMediaStreamSource(stream);

    // Каптура микрофона: AudioWorklet (устойчив в Chromium) с фолбэком на ScriptProcessor.
    if (ctx.audioWorklet) {
      try {
        await this.mountWorklet(ctx, src);
      } catch (err) {
        this.dbg({ ev: "worklet_fail", err: String((err as Error)?.message ?? err) });
      }
    }
    if (this.workletNode == null) {
      // фолбэк: ScriptProcessor
      const sp = ctx.createScriptProcessor(4096, 1, 1);
      sp.onaudioprocess = (e) => {
        if (this.state.muted) return;
        const input = e.inputBuffer.getChannelData(0);
        const merged = new Float32Array(this.encBuffer.length + input.length);
        merged.set(this.encBuffer, 0);
        merged.set(input, this.encBuffer.length);
        let off = 0;
        while (merged.length - off >= FRAME_SAMPLES) {
          this.pushFrame(merged.subarray(off, off + FRAME_SAMPLES));
          off += FRAME_SAMPLES;
        }
        this.encBuffer = merged.slice(off);
        this.lastOnProc = performance.now();
      };
      src.connect(sp);
      const gain = ctx.createGain();
      gain.gain.value = 0;
      sp.connect(gain);
      gain.connect(ctx.destination);
      this.script = sp;
    }
    this.dbg({ ev: "mic_path", micPath: this.workletNode ? "worklet" : "scriptproc" });
    this.startWatchdog();

    const encoder = new AudioEncoder({
      output: (chunk) => {
        try {
          if (this.state.phase !== "active" || this.state.muted) return;
          if (this.callId == null) return;
          if (this.roomId == null && this.peerId == null) return;
          const bytes = new Uint8Array(chunk.byteLength);
          chunk.copyTo(bytes);
          // основной путь — бинарный кадр: на 33% меньше трафика и без base64.
          // Сокет не готов -> откатываемся на /ws, чтобы не терять звук.
          if (!this.sendMediaFrame(MK_AUDIO, bytes)) {
            const sig: Record<string, unknown> = {
              type: "call_audio",
              call_id: this.callId,
              seq: callSeq++,
              audio: b64encode(bytes),
            };
            if (this.roomId != null) sig.room_id = this.roomId;
            else sig.to_id = this.peerId!;
            this.signal(sig);
          }
          if (this.dbSent % 50 === 0) {
            this.dbg({ ev: "enc_out", sent: this.dbSent, enc: this.encoder ? this.encoder.state : "none" });
          }
          this.dbSent++;
        } catch (err) {
          // иначе исключение здесь убило бы AudioEncoder (WebCodecs)
          this.dbg({ ev: "enc_out_err", err: String((err as Error)?.message ?? err) });
        }
      },
      error: (err) => {
        this.dbg({ ev: "enc_err", err: String((err as Error)?.message ?? err) });
      },
    });
    encoder.configure({
      codec: "opus",
      sampleRate: SAMPLE_RATE,
      numberOfChannels: 1,
      bitrate: 24000,
    });
    this.encoder = encoder;
  }

  private pushFrame(samples: Float32Array): void {
    if (!this.encoder || this.encoder.state !== "configured") return;
    const copy = samples.slice(); // ArrayBuffer-копия кадра (WebCodecs захватывает данные)
    const audioData = new AudioData({
      format: "f32-planar",
      sampleRate: SAMPLE_RATE,
      numberOfFrames: copy.length,
      numberOfChannels: 1,
      timestamp: this.encTs,
      data: copy,
    });
    this.encTs += FRAME_US;
    this.encoder.encode(audioData);
    audioData.close();
  }

  /** Микрофон через AudioWorklet: 20мс-кадры приходят из аудио-потока по port.postMessage. */
  private async mountWorklet(ctx: AudioContext, src: MediaStreamAudioSourceNode): Promise<void> {
    const procSrc = `
      class MicCapture extends AudioWorkletProcessor {
        constructor() {
          super();
          this.port.onmessage = (e) => {
            const data = e.data;
            this.port.postMessage(data, [data.buffer]);
          };
        }
        process(inputs, outputs) {
          const input = inputs[0];
          if (!input || !input[0]) return true;
          const ch = input[0];
          const copy = new Float32Array(ch.length);
          copy.set(ch);
          this.port.postMessage(copy, [copy.buffer]);
          return true;
        }
      }
      registerProcessor("mic-capture", MicCapture);
    `;
    const url = URL.createObjectURL(new Blob([procSrc], { type: "application/javascript" }));
    try {
      await ctx.audioWorklet.addModule(url);
      const node = new AudioWorkletNode(ctx, "mic-capture");
      node.port.onmessage = (e: MessageEvent) => {
        if (this.state.muted) return;
        this.lastOnProc = performance.now();
        this.pushFrame(e.data as Float32Array);
      };
      src.connect(node);
      node.connect(ctx.destination);
      this.workletNode = node;
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  /** Watchdog: телеметрия раз в секунду + автолечение микрофонного стопора. */
  private startWatchdog(): void {
    this.stopWatchdog();
    this.lastOnProc = performance.now();
    this.watchdog = window.setInterval(() => {
      const stallMs = Math.round(performance.now() - this.lastOnProc);
      let decIn = 0, decPlayed = 0, q = 0;
      for (const p of this.peers.values()) {
        decIn += p.decIn;
        decPlayed += p.decPlayed;
        q += p.decBuffer.length;
      }
      this.dbg({
        ev: "wdt",
        phase: this.state.phase,
        ctx: this.ctx ? this.ctx.state : "none",
        play: this.ctxPlay ? this.ctxPlay.state : "none",
        ws: this.wsStateGetter(),
        enc: this.encoder ? this.encoder.state : "none",
        peers: this.peers.size,
        stallMs,
        decIn,
        decPlayed,
        q,
      });
      if (this.ctx && this.ctx.state === "suspended") {
        void this.ctx.resume();
      }
      if (this.state.phase === "active" && stallMs > 1500 && this.stream) {
        this.dbg({ ev: "mic_stall", stallMs, action: "rebuild" });
        void this.rebuildMicPipeline();
      }
    }, 1000);
  }

  private stopWatchdog(): void {
    if (this.watchdog != null) {
      window.clearInterval(this.watchdog);
      this.watchdog = null;
    }
  }

  /** Пересоздать захват микрофона (если аудио-поток замолчал). */
  private async rebuildMicPipeline(): Promise<void> {
    try {
      const { stream, cfg } = await this.grabMic();
      const ctx = this.ctx;
      if (!ctx || this.state.phase !== "active") {
        for (const t of stream.getTracks()) t.stop();
        return;
      }
      this.dbg({ ev: "mic_rebuild", cfg });
      if (this.stream) for (const t of this.stream.getTracks()) t.stop();
      this.stream = stream;
      const src = ctx.createMediaStreamSource(stream);
      if (this.workletNode) {
        try { this.workletNode.disconnect(); } catch { /* noop */ }
        if (ctx.audioWorklet) {
          const node = new AudioWorkletNode(ctx, "mic-capture");
          node.port.onmessage = (e: MessageEvent) => {
            if (this.state.muted) return;
            this.lastOnProc = performance.now();
            this.pushFrame(e.data as Float32Array);
          };
          src.connect(node);
          node.connect(ctx.destination);
          this.workletNode = node;
          return;
        }
      }
      const sp = ctx.createScriptProcessor(4096, 1, 1);
      sp.onaudioprocess = (e2: AudioProcessingEvent) => {
        if (this.state.muted) return;
        const input = e2.inputBuffer.getChannelData(0);
        const merged = new Float32Array(this.encBuffer.length + input.length);
        merged.set(this.encBuffer, 0);
        merged.set(input, this.encBuffer.length);
        let off = 0;
        while (merged.length - off >= FRAME_SAMPLES) {
          this.pushFrame(merged.subarray(off, off + FRAME_SAMPLES));
          off += FRAME_SAMPLES;
        }
        this.encBuffer = merged.slice(off);
        this.lastOnProc = performance.now();
      };
      src.connect(sp);
      const gain = ctx.createGain();
      gain.gain.value = 0;
      sp.connect(gain);
      gain.connect(ctx.destination);
      this.script = sp;
    } catch {
      /* noop */
    }
  }

  // ---------- приём: декодер + джиттер-буфер на каждого собеседника ----------

  private ensurePeer(id: number): RemotePeer {
    let p = this.peers.get(id);
    if (!p) {
      p = { rxSeq: 0, decoder: null, decBuffer: [], nextTime: null, decIn: 0, decPlayed: 0, decFirst: false };
      this.peers.set(id, p);
    }
    if (!p.decoder && this.codecsOk()) {
      const decoder = new AudioDecoder({
        output: (audioData) => {
          this.handleDecoded(id, audioData);
        },
        error: (err) => {
          this.dbg({ ev: "dec_err", peer: id, err: String((err as Error)?.message ?? err) });
        },
      });
      decoder.configure({ codec: "opus", sampleRate: SAMPLE_RATE, numberOfChannels: 1 });
      p.decoder = decoder;
      p.nextTime = null;
      p.decBuffer = [];
    }
    return p;
  }

  private removePeer(id: number): void {
    const p = this.peers.get(id);
    if (p) {
      try {
        p.decoder?.close();
      } catch {
        /* noop */
      }
      this.peers.delete(id);
    }
  }

  private handleDecoded(peerId: number, audioData: AudioData): void {
    const peer = this.peers.get(peerId);
    try {
      if (!this.ctxPlay || !peer || this.state.phase === "idle" || this.state.phase === "incoming" || this.state.phase === "ended") {
        audioData.close();
        return;
      }
      const frames = audioData.numberOfFrames;
      const ch = Math.min(1, audioData.numberOfChannels);
      const buf = this.ctxPlay.createBuffer(ch, frames, audioData.sampleRate);
      const tmp = new Float32Array(frames);
      audioData.copyTo(tmp, { planeIndex: 0 });
      buf.copyToChannel(tmp, 0, 0);
      const rate = audioData.sampleRate;
      audioData.close();
      peer.decBuffer.push(buf);
      peer.decIn++;
      if (!peer.decFirst) {
        peer.decFirst = true;
        this.dbg({ ev: "dec_first", peer: peerId, frames, rate, phase: this.state.phase });
      } else if (peer.decIn % 30 === 0) {
        this.dbg({ ev: "dec_stream", peer: peerId, decIn: peer.decIn, decPlayed: peer.decPlayed, q: peer.decBuffer.length });
      }
      this.schedulePlayback(peer);
    } catch (err) {
      this.dbg({ ev: "dec_handle_err", err: String((err as Error)?.message ?? err) });
      audioData.close();
    }
  }

  private schedulePlayback(peer: RemotePeer): void {
    if (!this.ctxPlay) return;
    // завал: не копим бесконечно, иначе рендер-кванты аудио-потока захлебнутся
    if (peer.decBuffer.length > 100) {
      peer.decBuffer.splice(0, peer.decBuffer.length - 100);
    }
    const now = this.ctxPlay.currentTime;
    if (peer.nextTime == null || peer.nextTime < now - 0.05) {
      // старт или рассинхрон после сетевой задержки: сначала накопи стартовую пачку,
      // затем играем с запасом PREBUFFER_MS — джиттер-буфер против "рваного" звука
      if (peer.decBuffer.length < START_FRAMES) return;
      peer.nextTime = now + PREBUFFER_MS / 1000;
    }
    while (peer.decBuffer.length) {
      const buf = peer.decBuffer.shift()!;
      const src = this.ctxPlay.createBufferSource();
      src.buffer = buf;
      src.connect(this.ctxPlay.destination);
      src.start(peer.nextTime);
      peer.nextTime += buf.duration;
      peer.decPlayed++;
    }
  }

  private teardownAudio(): void {
    this.stopWatchdog();
    if (this.workletNode) {
      try {
        this.workletNode.disconnect();
      } catch {
        /* noop */
      }
      this.workletNode = null;
    }
    if (this.script) {
      try {
        this.script.disconnect();
        this.script.onaudioprocess = null;
      } catch {
        /* noop */
      }
      this.script = null;
    }
    if (this.encoder) {
      try {
        this.encoder.close();
      } catch {
        /* noop */
      }
      this.encoder = null;
    }
    for (const p of this.peers.values()) {
      try {
        p.decoder?.close();
      } catch {
        /* noop */
      }
    }
    this.peers.clear();
    if (this.stream) {
      for (const t of this.stream.getTracks()) t.stop();
      this.stream = null;
    }
    if (this.ctx) {
      try {
        void this.ctx.close();
      } catch {
        /* noop */
      }
      this.ctx = null;
    }
    if (this.ctxPlay && this.ctxPlay !== this.ctx) {
      try {
        void this.ctxPlay.close();
      } catch {
        /* noop */
      }
    }
    this.ctxPlay = null;
    this.encBuffer = new Float32Array(0);
    this.encTs = 0;
  }

  // ---------- outgoing (1-к-1) ----------

  async start(peerId: number): Promise<void> {
    if (this.state.phase !== "idle" && this.state.phase !== "ended") return;
    const g = ++this.gen;
    this.clearEndTimer();
    this.clearRingTimer();
    this.teardownAudio();
    this.peerId = peerId;
    this.roomId = null;
    this.inviterId = null;
    this.callId = "c" + Date.now().toString(36) + (callSeq++).toString(36) + Math.random().toString(36).slice(2, 8);
    this.setState({ phase: "outgoing", peerId, roomId: null, inviterId: null, startedAt: null, muted: false, reason: "", participants: [] });
    this.ringTimer = window.setTimeout(() => this.hangup("Абонент не ответил"), RING_TIMEOUT_MS);
    // Инвайт уходит сразу, не дожидаясь захвата микрофона, — иначе при зависшем/заблокированном
    // запросе разрешения собеседник вообще не увидел бы входящий звонок.
    this.signal({ type: "call", to_id: peerId, call_id: this.callId });
    // Декодер поднимаем сразу: если собеседник ответит, пока висит запрос микрофона,
    // первые кадры от него не потеряются.
    this.ensurePeer(peerId);
    try {
      await this.startMicAndEncoder();
      if (g !== this.gen) return;
      // Собеседник мог успеть ответить (call_answer уже перевёл в active) — фазу не затираем,
      // иначе застрянем в "connecting": не шлём аудио и не играем входящее (тишина с обеих сторон).
      if (phaseIs(this.state.phase, "outgoing")) this.setState({ phase: "connecting" });
    } catch (e) {
      if (g !== this.gen) return;
      const reason = e instanceof Error && e.message === "no-codecs"
        ? "WebView2 не поддерживает кодирование Opus"
        : "Нет доступа к микрофону";
      if (this.peerId != null && this.callId) {
        this.signal({ type: "call_hangup", to_id: this.peerId, call_id: this.callId, reason: "mic" });
      }
      this.end(reason);
    }
  }

  // ---------- голосовой канал комнаты ----------

  /** Войти в голосовой канал комнаты (создать, если пустой): сразу active,
   *  без дозвона — остальные участники увидят анонс и смогут войти. */
  async startRoomCall(roomId: number): Promise<void> {
    if (this.state.phase !== "idle" && this.state.phase !== "ended") return;
    const g = ++this.gen;
    this.clearEndTimer();
    this.clearRingTimer();
    this.teardownAudio();
    this.roomId = roomId;
    this.peerId = null;
    this.inviterId = null;
    this.callId = "c" + Date.now().toString(36) + (callSeq++).toString(36) + Math.random().toString(36).slice(2, 8);
    // канал не «звонит»: участники присоединяются сами по анонсу
    this.signal({ type: "call", room_id: roomId, call_id: this.callId });
    this.setState({ phase: "connecting", roomId, peerId: null, inviterId: null, startedAt: null, muted: false, reason: "", participants: [] });
    try {
      await this.startMicAndEncoder();
      if (g !== this.gen) return;
      this.setState({ phase: "active", startedAt: Date.now() });
    } catch (e) {
      if (g !== this.gen) return;
      const reason = e instanceof Error && e.message === "no-codecs"
        ? "WebView2 не поддерживает кодирование Opus"
        : "Нет доступа к микрофону";
      if (this.roomId != null && this.callId) {
        this.signal({ type: "call_hangup", room_id: this.roomId, call_id: this.callId, reason: "mic" });
      }
      this.end(reason);
    }
  }

  /** Принять приглашение в голосовой канал и войти. */
  private async acceptChannel(): Promise<void> {
    if (this.state.phase !== "incoming" || this.roomId == null) return;
    const g = ++this.gen;
    this.clearRingTimer();
    this.setState({ phase: "connecting", startedAt: null, reason: "" });
    // входим: остальные участники добавят нас по этому событию
    if (this.callId) {
      this.signal({ type: "call_answer", room_id: this.roomId, call_id: this.callId });
    }
    try {
      await this.startMicAndEncoder();
      if (g !== this.gen) return;
      this.setState({ phase: "active", startedAt: Date.now() });
    } catch (e) {
      if (g !== this.gen) return;
      const reason = e instanceof Error && e.message === "no-codecs"
        ? "WebView2 не поддерживает декодирование Opus"
        : "Нет доступа к микрофону";
      if (this.roomId != null && this.callId) {
        this.signal({ type: "call_hangup", room_id: this.roomId, call_id: this.callId, reason: "mic" });
      }
      this.end(reason);
    }
  }

  /** Кто-то в канале: добавляем участника и поднимаем декодер его голоса. */
  private addParticipant(id: number): void {
    this.ensurePeer(id);
    const list = this.state.participants;
    if (list.some((p) => p.id === id)) return;
    this.setState({ participants: [...list, { id, screen: false }] });
  }

  /** Участник вышел из канала: закрываем его декодер и убираем из списка. */
  private removeParticipant(id: number): void {
    this.removePeer(id);
    this.closeScreen(id);
    this.setState({ participants: this.state.participants.filter((p) => p.id !== id) });
  }

  private setPeerScreen(id: number, on: boolean): void {
    this.setState({
      participants: this.state.participants.map((p) => (p.id === id ? { ...p, screen: on } : p)),
      screenActive: this.state.peerId === id || this.state.peerId == null ? on : this.state.screenActive,
    });
  }

  // ---------- callee ----------

  async accept(): Promise<void> {
    if (this.roomId != null && this.state.phase === "incoming") {
      await this.acceptChannel();
      return;
    }
    if (this.state.phase !== "incoming") return;
    const g = ++this.gen;
    this.clearRingTimer();
    this.setState({ phase: "connecting", startedAt: null, reason: "" });
    this.ensurePeer(this.peerId!);
    // answer уходит сразу: собеседник переходит в active и начинает слать аудио,
    // пока мы параллельно поднимаем микрофон.
    if (this.peerId != null && this.callId) {
      this.signal({ type: "call_answer", to_id: this.peerId, call_id: this.callId });
    }
    try {
      await this.startMicAndEncoder();
      if (g !== this.gen) return;
      this.setState({ phase: "active", startedAt: Date.now() });
    } catch (e) {
      if (g !== this.gen) return;
      const reason = e instanceof Error && e.message === "no-codecs"
        ? "WebView2 не поддерживает декодирование Opus"
        : "Нет доступа к микрофону";
      if (this.peerId != null && this.callId) {
        this.signal({ type: "call_hangup", to_id: this.peerId, call_id: this.callId, reason: "mic" });
      }
      this.end(reason);
    }
  }

  decline(): void {
    if (this.state.phase !== "incoming") return;
    if (this.roomId != null) {
      // канал продолжает жить без нас — ничего не шлём, просто выходим из инвайта
      this.end("Вы не вошли в канал");
      return;
    }
    if (this.peerId != null && this.callId) {
      this.signal({ type: "call_hangup", to_id: this.peerId, call_id: this.callId, reason: "declined" });
    }
    this.end("Звонок отклонён");
  }

  // ---------- common ----------

  hangup(reason = "Звонок завершён"): void {
    const ph = this.state.phase;
    if (ph === "idle" || ph === "ended") return;
    if (this.roomId != null && this.callId) {
      this.signal({ type: "call_hangup", room_id: this.roomId, call_id: this.callId, reason: reason === "Звонок завершён" ? "leave" : reason });
    } else if (this.peerId != null && this.callId) {
      this.signal({ type: "call_hangup", to_id: this.peerId, call_id: this.callId, reason });
    }
    this.end(reason);
  }

  toggleMute(): void {
    if (!this.encoder) return;
    const muted = !this.state.muted;
    if (this.stream) {
      const t = this.stream.getAudioTracks()[0];
      if (t) t.enabled = !muted;
    }
    this.setState({ muted });
  }

  /** Транспорт снова подключён (WS пережил обрыв туннеля): в голосовом канале
   *  повторяем анонс присутствия, чтобы участники (и свежие) снова нас видели.
   *  Для 1-1 ничего не нужно — потоки аудио возобновятся сами после реконнекта. */
  onTransportBack(): void {
    if (this.roomId != null && this.callId != null && (this.state.phase === "active" || this.state.phase === "connecting")) {
      this.signal({ type: "call", room_id: this.roomId, call_id: this.callId });
    }
  }

  // ---------- демонстрация экрана ----------

  /** Холст, в который рисуем входящие кадры конкретного участника (управляет оверлей). */
  setScreenCanvas(peerId: number | null, el: HTMLCanvasElement | null): void {
    if (peerId == null) return;
    let scr = this.screens.get(peerId);
    if (scr) scr.canvas = el;
    if (el) {
      const ctx = el.getContext("2d");
      ctx?.clearRect(0, 0, el.width, el.height);
    }
  }

  async startScreenShare(): Promise<void> {
    if (this.state.phase !== "active" || this.screenTrack) return;
    const W = window as any;
    if (!W.VideoEncoder || !W.VideoDecoder) {
      this.setState({ screenError: "WebView2 не поддерживает видео-кодеки" });
      return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) {
      this.setState({ screenError: "Нет поддержки захвата экрана" });
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: {
          width: { ideal: 1280, max: 1920 },
          height: { ideal: 720, max: 1080 },
          frameRate: { ideal: 20, max: 30 },
        },
        audio: false,
      });
      if (this.state.phase !== "active") {
        for (const t of stream.getTracks()) t.stop();
        return;
      }
      this.screenStream = stream;
      const track = stream.getVideoTracks()[0];
      if (!track) throw new Error("Нет видео-трека");
      this.screenTrack = track;
      track.addEventListener("ended", () => this.stopScreenShare()); // пользователь закрыл захват

      const settings = track.getSettings();
      let w = Math.min(Math.round(settings.width || 1280), 1280);
      let h = Math.min(Math.round(settings.height || 720), 720);
      w -= w % 2;
      h -= h % 2;
      if (w < 160) w = 160;
      if (h < 90) h = 90;

      const codec = await this.pickVideoCodec(w, h);
      if (!codec) {
        this.teardownScreenShare();
        this.setState({ screenError: "Нет поддерживаемого видео-кодека (VP8/VP9/AV1)" });
        return;
      }
      this.screenBitrate = 1_200_000;
      this.screenBytes = 0;
      this.screenAdaptAt = performance.now();
      this.screenFrameAt = 0;
      this.screenForceKey = true;
      this.setupScreenEncoder(codec, w, h);

      // сигнал: начинаем демонстрацию (в канал — комнате, иначе — собеседнику)
      if (this.callId) {
        const sig: Record<string, unknown> = { type: "screen_start", call_id: this.callId, codec, width: w, height: h };
        if (this.roomId != null) sig.room_id = this.roomId;
        else sig.to_id = this.peerId!;
        this.signal(sig);
      }
      this.setState({ screenOn: true, screenError: "" });

      // читаем кадры: MediaStreamTrackProcessor или скрытый <video>
      if (stream && W.MediaStreamTrackProcessor) {
        try {
          const proc = new W.MediaStreamTrackProcessor({ track });
          this.screenProcessor = proc;
          const reader = proc.readable.getReader();
          this.screenReader = reader;
          void this.screenReadLoop();
        } catch {
          this.startScreenVideoCapture();
        }
      } else {
        this.startScreenVideoCapture();
      }
    } catch (e) {
      this.teardownScreenShare();
      const msg = e instanceof Error && e.name === "NotAllowedError"
        ? "Захват экрана запрещён"
        : e instanceof Error ? e.message : "Не удалось захватить экран";
      this.setState({ screenError: msg });
    }
  }

  private async screenReadLoop(): Promise<void> {
    const reader = this.screenReader;
    if (!reader) return;
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done || !value) break;
        if (this.state.phase !== "active" || !this.screenTrack) {
          (value as VideoFrame).close();
          break;
        }
        this.encodeScreenFrame(value as VideoFrame);
      }
    } catch {
      /* noop */
    } finally {
      this.screenReader = null;
    }
  }

  private startScreenVideoCapture(): void {
    if (!this.screenStream) return;
    const video = document.createElement("video");
    video.muted = true;
    video.playsInline = true;
    video.autoplay = true;
    video.srcObject = this.screenStream;
    video.style.position = "fixed";
    video.style.width = "2px";
    video.style.height = "2px";
    video.style.opacity = "0";
    video.style.pointerEvents = "none";
    document.body.appendChild(video);
    this.screenVideo = video;
    const W = window as any;
    const tick = () => {
      if (!this.screenVideo || !video.videoWidth) {
        if (this.screenVideo === video) {
          // видеопоток ещё не готов — подождём кадр
          try { video.requestVideoFrameCallback(tick); } catch { /* noop */ }
        }
        return;
      }
      const vf = new W.VideoFrame(video, { timestamp: performance.now() * 1000 });
      this.encodeScreenFrame(vf);
      if (this.screenVideo === video) video.requestVideoFrameCallback(tick);
    };
    video.requestVideoFrameCallback(tick);
  }

  private encodeScreenFrame(frame: VideoFrame): void {
    const enc = this.screenEncoder;
    if (!enc || enc.state !== "configured" || !this.screenTrack) {
      try { frame.close(); } catch { /* noop */ }
      return;
    }
    // троттлинг: не быстрее ~20 fps
    const now = performance.now();
    const minGap = 50;
    if (now - this.screenFrameAt < minGap) {
      try { frame.close(); } catch { /* noop */ }
      return;
    }
    this.screenFrameAt = now;
    // адаптация битрейта раз в ~2.5 c
    if (now - this.screenAdaptAt > 2500) {
      this.adaptScreenBitrate(now);
      this.screenAdaptAt = now;
      this.screenBytes = 0;
    }
    try {
      enc.encode(frame, { keyFrame: this.screenForceKey });
      this.screenForceKey = false;
    } catch { /* noop */ }
    try { frame.close(); } catch { /* noop */ }
  }

  private adaptScreenBitrate(now: number): void {
    if (!this.screenEncoder || this.screenEncoder.state !== "configured") return;
    const dt = (now - this.screenAdaptAt) / 1000 || 1;
    const bps = (this.screenBytes * 8) / dt;
    // цель — уложиться в ~80% битрейта
    if (bps > this.screenBitrate * 0.8 && this.screenBitrate > 300_000) {
      this.screenBitrate = Math.max(300_000, Math.round(this.screenBitrate * 0.75));
    } else if (bps < this.screenBitrate * 0.4 && this.screenBitrate < 2_500_000) {
      this.screenBitrate = Math.round(this.screenBitrate * 1.2);
    }
  }

  private async pickVideoCodec(w: number, h: number): Promise<string | null> {
    const W = window as any;
    const candidates = ["vp09.00.10.08", "vp8", "av01.0.04M.08"];
    for (const codec of candidates) {
      try {
        const res = await W.VideoEncoder.isConfigSupported({
          codec,
          width: w,
          height: h,
          bitrate: 1_200_000,
          framerate: 20,
        });
        if (res && res.supported) return codec;
      } catch { /* пробуем следующий */ }
    }
    return null;
  }

  private setupScreenEncoder(codec: string, w: number, h: number): void {
    if (this.screenEncoder) {
      try { this.screenEncoder.close(); } catch { /* noop */ }
    }
    const enc = new VideoEncoder({
      output: (chunk) => {
        if (this.state.phase !== "active" || !this.screenTrack) return;
        if (this.callId == null) return;
        const bytes = new Uint8Array(chunk.byteLength);
        chunk.copyTo(bytes);
        this.screenBytes += bytes.byteLength;
        // видео — тоже бинарным кадром: на 33% меньше трафика и без base64.
        // Сокет не готов -> откат на /ws, чтобы демка не рассыпалась.
        this.screenSeq++;
        if (!this.sendMediaFrame(MK_VIDEO, bytes)) {
          const sig: Record<string, unknown> = {
            type: "screen_frame",
            call_id: this.callId,
            seq: this.screenSeq,
            key: chunk.type === "key",
            data: b64encode(bytes),
          };
          if (this.roomId != null) sig.room_id = this.roomId;
          else sig.to_id = this.peerId!;
          this.signal(sig);
        }
        // каждые ~120 кадров ключевой (чтобы входящий мог «догнать»)
        if (this.screenSeq % 150 === 0) this.screenForceKey = true;
      },
      error: () => undefined,
    });
    enc.configure({
      codec,
      width: w,
      height: h,
      bitrate: this.screenBitrate,
      framerate: 20,
    });
    this.screenEncoder = enc;
  }

  stopScreenShare(): void {
    if (!this.screenTrack && !this.screenStream) {
      if (this.state.screenOn) this.setState({ screenOn: false });
      return;
    }
    if (this.callId) {
      const sig: Record<string, unknown> = { type: "screen_stop", call_id: this.callId };
      if (this.roomId != null) sig.room_id = this.roomId;
      else sig.to_id = this.peerId!;
      this.signal(sig);
    }
    this.teardownScreenShare();
    this.setState({ screenOn: false });
  }

  private teardownScreenShare(): void {
    this.screenReader?.cancel().catch(() => undefined);
    this.screenReader = null;
    try { this.screenProcessor?.stop?.(); } catch { /* noop */ }
    this.screenProcessor = null;
    if (this.screenStream) {
      for (const t of this.screenStream.getTracks()) t.stop();
      this.screenStream = null;
    }
    if (this.screenVideo) {
      try {
        this.screenVideo.srcObject = null;
        this.screenVideo.remove();
      } catch { /* noop */ }
      this.screenVideo = null;
    }
    if (this.screenEncoder) {
      try { this.screenEncoder.close(); } catch { /* noop */ }
      this.screenEncoder = null;
    }
    this.screenTrack = null;
    this.screenBytes = 0;
  }

  /** Поднять декодер чужой демонстрации экрана (1-1: peerId; канал: любой участник). */
  private ensureScreen(from: number, codec: string): void {
    // демонстрация могла перезапуститься — старый декодер закрываем
    this.closeScreen(from);
    const dec = new VideoDecoder({
      output: (frame) => {
        this.drawScreenFrame(from, frame);
      },
      error: () => undefined,
    });
    dec.configure({ codec });
    this.screens.set(from, { rxSeq: 0, decoder: dec, canvas: null });
  }

  private drawScreenFrame(from: number, frame: VideoFrame): void {
    try {
      const scr = this.screens.get(from);
      const el = scr?.canvas;
      if (!el || this.state.phase !== "active") {
        frame.close();
        return;
      }
      const w = frame.displayWidth || frame.codedWidth;
      const h = frame.displayHeight || frame.codedHeight;
      if (el.width !== w) el.width = w;
      if (el.height !== h) el.height = h;
      const ctx = el.getContext("2d");
      if (ctx) ctx.drawImage(frame, 0, 0, w, h);
    } catch { /* noop */ }
    try { frame.close(); } catch { /* noop */ }
  }

  private closeScreen(from: number): void {
    const scr = this.screens.get(from);
    if (scr) {
      try {
        scr.decoder?.close();
      } catch {
        /* noop */
      }
      this.screens.delete(from);
    }
  }

  private closeAllScreens(): void {
    for (const from of Array.from(this.screens.keys())) this.closeScreen(from);
  }

  private end(reason: string): void {
    const g = ++this.gen;
    this.clearRingTimer();
    this.clearEndTimer();
    this.teardownAudio();
    this.stopScreenShare();
    this.closeAllScreens();
    this.setState({ phase: "ended", reason, startedAt: null, muted: false, screenActive: false, participants: [], peerId: this.peerId, roomId: this.roomId });
    this.endTimer = window.setTimeout(() => {
      if (g !== this.gen) return;
      this.peerId = null;
      this.roomId = null;
      this.inviterId = null;
      this.setState({ phase: "idle", reason: "", startedAt: null, peerId: null, roomId: null, inviterId: null, participants: [] });
    }, END_TO_IDLE_MS);
  }

  // ---------- events from WS ----------

  handleEvent(ev: WsEvent): void {
    const from = ev.from_id;
    if (from == null || from === this.meId) return; // сервер релеит и отправителю тоже
    const evRoom = ev.room_id != null ? Number(ev.room_id) : null;
    const ty = ev.type;

    // ---------- голосовой канал комнаты (room_id без to_id) ----------
    if (evRoom != null && ev.to_id == null) {
      if (ty === "call") {
        // анонс: кто-то вошёл в канал комнаты
        if (this.roomId === evRoom && (this.state.phase === "active" || this.state.phase === "connecting")) {
          this.addParticipant(from); // присутствие: анонс = он уже в канале
        } else if (this.state.phase === "idle" || this.state.phase === "ended") {
          this.clearEndTimer(); // канал в окне «ended» — не дать таймеру сбросить его в idle
          this.roomId = evRoom;
          this.callId = ev.call_id ?? null;
          this.inviterId = from;
          this.setState({
            phase: "incoming", roomId: evRoom, inviterId: from, peerId: null,
            muted: false, reason: "", startedAt: null,
            participants: [{ id: from, screen: false }],
          });
        }
        // заняты другим звонком — молча игнорируем (канал без нас)
        return;
      }
      if (ty === "call_answer") {
        if (this.roomId !== evRoom) return;
        if (this.state.phase === "active" || this.state.phase === "connecting") this.addParticipant(from);
        return;
      }
      if (ty === "call_audio") {
        if (this.roomId !== evRoom || !ev.audio || this.callId !== ev.call_id) return;
        if (this.state.phase !== "active" && this.state.phase !== "connecting") return;
        this.addParticipant(from); // догоняем участника, чей анонс могли пропустить
        const peer = this.ensurePeer(from);
        if (!peer.decoder || peer.decoder.state !== "configured") return;
        try {
          const bytes = b64decode(ev.audio);
          const chunk = new EncodedAudioChunk({
            type: "key",
            timestamp: (ev.seq ?? 0) * FRAME_US,
            data: bytes,
          });
          peer.decoder.decode(chunk);
        } catch {
          /* noop */
        }
        return;
      }
      if (ty === "call_hangup") {
        if (this.roomId !== evRoom) return;
        if (this.state.phase === "incoming" && this.inviterId === from) {
          // позвавший закрыл канал, не дождавшись нас — выходим из инвайта
          this.end("Канал закрыт");
          return;
        }
        this.removeParticipant(from);
        return;
      }
      if (ty === "screen_start") {
        if (this.roomId !== evRoom) return;
        if (this.state.phase !== "active" && this.state.phase !== "connecting") return;
        this.ensureScreen(from, ev.codec || "vp8");
        this.setPeerScreen(from, true);
        return;
      }
      if (ty === "screen_frame") {
        if (this.roomId !== evRoom || !ev.data || this.callId !== ev.call_id) return;
        if (this.state.phase !== "active") return;
        const scr = this.screens.get(from);
        if (!scr || !scr.decoder || scr.decoder.state !== "configured") return;
        try {
          const bytes = b64decode(ev.data);
          const chunk = new EncodedVideoChunk({
            type: ev.key ? "key" : "delta",
            timestamp: (ev.seq ?? 0) * 1_000,
            data: bytes,
          });
          // не копим очередь: если декодер завален — пропускаем кадр
          if (scr.decoder.decodeQueueSize > 3) return;
          scr.decoder.decode(chunk);
        } catch { /* noop */ }
        return;
      }
      if (ty === "screen_stop") {
        if (this.roomId !== evRoom) return;
        this.closeScreen(from);
        this.setPeerScreen(from, false);
        return;
      }
      return;
    }

    // ---------- 1-к-1 звонок ----------
    const sy = from !== this.peerId; // не нашёл свой звонок?

    if (ty === "call") {
      // входящий звонок
      if (this.state.phase !== "idle" && this.state.phase !== "ended") {
        // заняты (или уже в звонке/канале) — автоотбой
        this.signal({ type: "call_hangup", to_id: from, call_id: ev.call_id ?? null, reason: "busy" });
        return;
      }
      this.clearEndTimer(); // новый звонок в окне «ended» — не дать таймеру сбросить его в idle
      this.peerId = from;
      this.roomId = null;
      this.inviterId = null;
      this.callId = ev.call_id ?? null;
      this.setState({ phase: "incoming", peerId: from, roomId: null, inviterId: null, muted: false, reason: "", participants: [] });
      this.clearRingTimer();
      this.ringTimer = window.setTimeout(() => {
        if (this.state.phase === "incoming") this.end("Вызов пропущен");
      }, RING_TIMEOUT_MS);
      return;
    }

    if (ty === "call_answer") {
      if (sy || this.callId !== ev.call_id) return;
      if (this.state.phase === "connecting" || this.state.phase === "outgoing") {
        this.clearRingTimer(); // ответ получен — таймер "не ответил" больше не нужен
        this.setState({ phase: "active", startedAt: Date.now() });
      }
      return;
    }

    if (ty === "call_audio") {
      if (sy || !ev.audio || this.callId !== ev.call_id) return;
      if (this.state.phase === "idle" || this.state.phase === "incoming" || this.state.phase === "ended") return;
      const peer = this.ensurePeer(from);
      if (!peer.decoder || peer.decoder.state !== "configured") return;
      try {
        const bytes = b64decode(ev.audio);
        const chunk = new EncodedAudioChunk({
          type: "key",
          timestamp: (ev.seq ?? 0) * FRAME_US,
          data: bytes,
        });
        peer.decoder.decode(chunk);
      } catch {
        /* noop */
      }
      return;
    }

    if (ty === "call_hangup") {
      if (from !== this.peerId) return;
      let reason = "Собеседник завершил звонок";
      if (ev.reason === "busy") reason = "Абонент занят";
      else if (ev.reason === "declined") reason = "Собеседник отклонил звонок";
      else if (ev.reason === "mic") reason = "У собеседника нет микрофона";
      else if (this.state.phase === "outgoing" || this.state.phase === "incoming") reason = "Вызов завершён";
      this.end(reason);
      return;
    }

    if (ty === "screen_start") {
      if (sy || this.callId !== ev.call_id) return;
      this.ensureScreen(from, ev.codec || "vp8");
      this.setState({ screenActive: true, screenError: "" });
      return;
    }

    if (ty === "screen_frame") {
      if (sy || !ev.data || this.callId !== ev.call_id) return;
      if (this.state.phase !== "active") return;
      const scr = this.screens.get(from);
      if (!scr || !scr.decoder || scr.decoder.state !== "configured") return;
      try {
        const bytes = b64decode(ev.data);
        const chunk = new EncodedVideoChunk({
          type: ev.key ? "key" : "delta",
          timestamp: (ev.seq ?? 0) * 1_000,
          data: bytes,
        });
        // не копим очередь: если декодер завален — пропускаем кадр
        if (scr.decoder.decodeQueueSize > 3) return;
        scr.decoder.decode(chunk);
      } catch { /* noop */ }
      return;
    }

    if (ty === "screen_stop") {
      if (from !== this.peerId) return;
      this.closeScreen(from);
      this.setState({ screenActive: false });
      return;
    }
  }

  destroy(): void {
    const g = ++this.gen;
    this.clearRingTimer();
    this.clearEndTimer();
    this.teardownAudio();
    this.stopScreenShare();
    this.closeAllScreens();
    this.peerId = null;
    this.roomId = null;
    this.inviterId = null;
    this.setState({ phase: "idle", peerId: null, roomId: null, inviterId: null, startedAt: null, muted: false, screenActive: false, reason: "", participants: [] });
    void g;
  }

  /** Закрыть оверлей «завершено» сразу, не дожидаясь таймера. */
  dismiss(): void {
    if (this.state.phase !== "ended") return;
    const g = ++this.gen;
    this.clearRingTimer();
    this.clearEndTimer();
    this.peerId = null;
    this.roomId = null;
    this.inviterId = null;
    this.setState({ phase: "idle", peerId: null, roomId: null, inviterId: null, startedAt: null, muted: false, reason: "", participants: [] });
    void g;
  }
}