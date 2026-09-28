"""Юнит-тесты очередей приоритетов: порядок выдачи и отбрасывание.

Сетевой тест не может надёжно проверить переполнение (на loopback очередь
успевает опустошаться), поэтому проверяем сам OutQueue напрямую.
"""
import sys

sys.path.insert(0, r"D:\nekochat")

from app.config import settings
from app.ws_media import (
    FLAG_ROOM,
    KIND_AUDIO,
    KIND_FILE,
    KIND_VIDEO,
    PRIO_CTRL,
    PRIO_FILE,
    PRIO_VOICE,
    PRIO_VIDEO,
    OutQueue,
    build_frame,
    parse_frame,
)

ok, fail = 0, 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {name}")
    else:
        fail += 1
        print(f"  FAIL  {name} {extra}")


print("[A] приоритет выдачи: голос раньше control, потом видео, потом файл")
q = OutQueue({PRIO_VOICE: 10, PRIO_CTRL: 10, PRIO_VIDEO: 10, PRIO_FILE: 10})
q.put(PRIO_FILE, b"file")
q.put(PRIO_VIDEO, b"video")
q.put(PRIO_CTRL, b"ctrl")
q.put(PRIO_VOICE, b"voice")
order = []
while True:
    item = q.pop()
    if item is None:
        break
    order.append(item)
check("порядок выдачи voice -> ctrl -> video -> file",
      order == [b"voice", b"ctrl", b"video", b"file"], f"получено {order}")

print("\n[B] отбрасывание: переполненная видео-очередь не трогает голос")
q = OutQueue({PRIO_VOICE: 100, PRIO_VIDEO: 3, PRIO_FILE: 2})
for i in range(10):
    q.put(PRIO_VIDEO, f"v{i}".encode())
check("в видео-очереди осталось ровно cap=3", q.depth(PRIO_VIDEO) == 3, f"depth={q.depth(PRIO_VIDEO)}")
check("дропнуто 7 кадров", q.q if False else sum(q.dropped.values()) == 7, f"dropped={q.dropped}")
for i in range(50):
    q.put(PRIO_VOICE, f"a{i}".encode())
check("голос не пострадал (50 в очереди, cap=100)", q.depth(PRIO_VOICE) == 50, f"depth={q.depth(PRIO_VOICE)}")
check("голос выдаётся раньше видео", q.pop().startswith(b"a"), )

print("\n[C] отбрасывание: файлы рвутся первыми (одноразовые)")
q = OutQueue({PRIO_VOICE: 10, PRIO_VIDEO: 10, PRIO_FILE: 2})
for i in range(20):
    q.put(PRIO_FILE, f"f{i}".encode())
check("в файловой очереди cap=2", q.depth(PRIO_FILE) == 2, f"depth={q.depth(PRIO_FILE)}")
check("файлы дропнуты", q.dropped[PRIO_FILE] == 18, f"dropped={q.dropped[PRIO_FILE]}")
check("очередь пуста после pop", q.pop() is not None and q.pop() is not None and q.pop() is None)

print("\n[D] счётчик байтов сходится")
q = OutQueue({PRIO_VOICE: 100})
for i in range(10):
    q.put(PRIO_VOICE, b"x" * 1000)
check("bytes == 10000", q.bytes(PRIO_VOICE) == 10000, f"bytes={q.bytes(PRIO_VOICE)}")
for _ in range(10):
    q.pop()
check("bytes == 0 после опустошения", q.bytes(PRIO_VOICE) == 0, f"bytes={q.bytes(PRIO_VOICE)}")

print("\n[E] кадр туда-обратно без искажений")
for kind in (KIND_AUDIO, KIND_VIDEO, KIND_FILE):
    for flags in (0, FLAG_ROOM):
        for payload in (b"", b"x", bytes(range(256)) * 40):
            f = build_frame(kind, flags, 4242, payload)
            k, fl, t, p = parse_frame(f)
            if not (k == kind and fl == flags and t == 4242 and p == payload):
                check(f"roundtrip kind={kind} flags={flags} len={len(payload)}", False,
                      f"got {k},{fl},{t},{len(p)}")
                break
else:
    check("roundtrip для всех kind/flags/длин (18 комбинаций)", True)

print("\n[F] битые кадры отвергаются, а не роняют")
from app.ws_media import FrameError, IncompleteFrame

for name, blob in [
    ("короче заголовка", b"\x01\x01\x00\x00"),
    ("неверная версия", b"\xff\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"),
    ("неизвестный kind", bytes([1, 99, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])),
    ("length больше payload", bytes([1, 1, 0, 0, 0, 0, 0, 0, 10, 0, 0, 0]) + b"short"),
    ("length больше потолка", bytes([1, 1, 0, 0, 0, 0, 0, 0, 0xFF, 0xFF, 0xFF, 0xFF])),
]:
    try:
        parse_frame(blob)
        check(f"отвергнут: {name}", False, "принят!")
    except FrameError as e:
        check(f"отвергнут: {name}", True)

print("\n[G] неполный кадр отличается от мусора (буфер надо сохранить)")
try:
    parse_frame(bytes([1, 1, 0, 0, 0, 0, 0, 0, 10, 0, 0, 0]) + b"short")
    check("неполный кадр -> IncompleteFrame", False, "принят как валидный")
except IncompleteFrame:
    check("неполный кадр -> IncompleteFrame", True)
except FrameError:
    check("неполный кадр -> IncompleteFrame", False, "общий FrameError вместо IncompleteFrame")
# и он действительно IncompleteFrame (наследник) — приёмник ловит его первым
check("IncompleteFrame наследует FrameError", issubclass(IncompleteFrame, FrameError))

print(f"\n=== ИТОГ: {ok} passed, {fail} failed ===")
sys.exit(1 if fail else 0)
