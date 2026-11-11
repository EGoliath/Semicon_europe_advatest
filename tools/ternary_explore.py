#!/usr/bin/env python3
"""Ternary packing: overhead exploration + optimisation measurements.

    .venv/bin/python tools/ternary_explore.py            -> results/ternary_explore.md

Part A  escape-overhead study (exact packed sizes, packing only):
        naive escape vs in-band tokens (implemented) vs span blocks (size model)
Part B  optimisation steps: reference (Python/numpy) vs C, div/mod vs LUT,
        single-thread vs parallel blocks
Part C  t5 stream block-size sweep (size with / without zstd, speed)
Part D  stage timings: parse / pack / zstd for t5, t5row, mixed, bitpack
"""
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import zstandard as zstd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from patzstd import ternary as T, fast  # noqa: E402
from patzstd.codec import _compressor  # noqa: E402

EX = os.path.join(ROOT, "data", "extracted")
OUT = []


def say(s=""):
    print(s, flush=True)
    OUT.append(s)


def load(fid, max_bytes=None):
    p = os.path.join(EX, f"{fid}.pat", "Vectors.vec")
    with open(p, "rb") as f:
        first = f.readline()
        W = len(first) - 1
        f.seek(0)
        n = os.path.getsize(p) if max_bytes is None else min(max_bytes, os.path.getsize(p))
        n -= n % (W + 1)
        data = f.read(n)
    return data, W, n // (W + 1)


def timeit(fn, reps=3):
    best = 1e9
    for _ in range(reps):
        t = time.perf_counter()
        r = fn()
        best = min(best, time.perf_counter() - t)
    return best, r


def mbps(n, t):
    return n / 1e6 / t


def z9(b):
    return len(_compressor(9, -1, True).compress(bytes(b)))


def vlen(n):                       # LEB128 varint length
    k = 1
    while n >= 128:
        n >>= 7
        k += 1
    return k


def runs(mask):
    """lengths of alternating runs of a bool array, plus the first value."""
    if len(mask) == 0:
        return np.empty(0, np.int64), True
    edges = np.flatnonzero(np.diff(mask.astype(np.int8))) + 1
    bounds = np.concatenate(([0], edges, [len(mask)]))
    return np.diff(bounds), bool(mask[0])


# ------------------------------------------------------------------- part A
def part_a():
    say("## A. Escape-overhead study (packing only, exact sizes on a 16 MiB sample)")
    say("")
    say("Alphabet = 3 most frequent non-newline bytes of the sample.")
    say("* **naive escape**: every non-alphabet byte (incl. newline) = ESC + byte (2 B),")
    say("  partial group = marker + value (2 B)  — *size model*")
    say("* **in-band tokens** (implemented `t5`): newline = 1 token, partial = 2 B, other = 2 B")
    say("* **span blocks**: alternating varint-length spans, packed spans ⌈n/5⌉ B,")
    say("  raw spans verbatim — *size model*")
    say("* **t5row / mixed / bitpack**: implemented grid codecs")
    say("")
    say("| file | W | alphabet | naive escape | in-band t5 | span blocks | t5row | mixed | bitpack |")
    say("|---|---|---|---|---|---|---|---|---|")
    for fid in ("002", "004", "023", "003", "009", "001"):
        data, W, rows = load(fid, 16 << 20)
        n = len(data)
        a = T.stream_alphabet(data)
        lut = T.lut_from_alphabet(a)
        u = np.frombuffer(data, np.uint8)
        elig = lut[u] < 3
        ln, first = runs(elig)
        el = ln[0::2] if first else ln[1::2]          # eligible run lengths
        ot = ln[1::2] if first else ln[0::2]          # other run lengths
        part = (el % 5 != 0).sum()
        groups = (el // 5).sum()
        nl = int((u == 10).sum())
        other_bytes = int(ot.sum())
        naive = groups + 2 * part + 2 * other_bytes
        inband = len(T.stream_encode(data, a))
        span = sum(vlen(x) + (x + 4) // 5 for x in el) + sum(vlen(x) + x for x in ot)
        pres = np.zeros((W, 256), np.uint8)
        fast.analyse(data, rows, W, pres)
        syms = np.flatnonzero(pres.any(0))
        row = rows * ((W + 4) // 5) if len(syms) <= 3 else None
        if pres.sum(1).max() <= 3:
            cls, al, plut = T.pin_classes(pres)
            mixed = len(T.mixed_pack(data, rows, W, cls, plut))
        else:
            mixed = None
        bp = W * ((rows + 7) // 8) if pres.sum(1).max() <= 2 else None

        def f(x):
            return "n/a" if x is None else f"{n / x:.2f}x"
        say(f"| {fid} | {W} | `{bytes(a).decode()}` | {f(naive)} | {f(inband)} | {f(span)} | "
            f"{f(row)} | {f(mixed)} | {f(bp)} |")
        assert nl == rows
    say("")


# ------------------------------------------------------------------- part B
def part_b():
    say("## B. Optimisation steps (file 006, 01X alphabet, W=76)")
    say("")
    data, W, rows = load("006")
    n = len(data)
    a = T.stream_alphabet(data)
    sample = data[: 1 << 20]
    say(f"input {n / 1e6:.0f} MB; Python reference measured on a 1 MiB sample")
    say("")
    say("| codec | step | encode MB/s | decode MB/s |")
    say("|---|---|---|---|")
    # stream
    te, enc_s = timeit(lambda: T.stream_encode_ref(sample, a), 1)
    td, _ = timeit(lambda: T.stream_decode_ref(enc_s, a, len(sample)), 1)
    say(f"| t5 stream | pure Python reference | {mbps(len(sample), te):.1f} | {mbps(len(sample), td):.1f} |")
    blocks = [data[o:o + (1 << 20)] for o in range(0, n, 1 << 20)]
    alphs = [T.stream_alphabet(b) for b in blocks]
    te, encs = timeit(lambda: [T.stream_encode(b, x) for b, x in zip(blocks, alphs)])
    td_div, _ = timeit(lambda: [T.stream_decode(e, x, len(b), use_lut=False)
                                for e, x, b in zip(encs, alphs, blocks)])
    td_lut, _ = timeit(lambda: [T.stream_decode(e, x, len(b), use_lut=True)
                                for e, x, b in zip(encs, alphs, blocks)])
    say(f"| t5 stream | C, 1 thread, div/mod decode | {mbps(n, te):.0f} | {mbps(n, td_div):.0f} |")
    say(f"| t5 stream | C, 1 thread, LUT decode | {mbps(n, te):.0f} | {mbps(n, td_lut):.0f} |")
    with ThreadPoolExecutor(os.cpu_count()) as ex:
        te_p, _ = timeit(lambda: list(ex.map(T.stream_encode, blocks, alphs)))
        td_p, _ = timeit(lambda: list(ex.map(lambda e, x, b: T.stream_decode(e, x, len(b)),
                                             encs, alphs, blocks)))
        ta, _ = timeit(lambda: list(ex.map(T.stream_alphabet, blocks)))
    say(f"| t5 stream | C, parallel blocks ({os.cpu_count()} thr), LUT | {mbps(n, te_p):.0f} | {mbps(n, td_p):.0f} |")
    say(f"| t5 stream | (alphabet selection alone, parallel) | {mbps(n, ta):.0f} | – |")
    # row
    R = 1 << 20
    chunk = data[: R * (W + 1)]
    r = len(chunk) // (W + 1)
    te, e = timeit(lambda: T.row_pack_ref(chunk, r, W, a), 1)
    td, _ = timeit(lambda: T.row_unpack_ref(e, r, W, a), 1)
    say(f"| t5row | numpy reference | {mbps(len(chunk), te):.0f} | {mbps(len(chunk), td):.0f} |")
    te, e = timeit(lambda: T.row_pack(chunk, r, W, a))
    td1, _ = timeit(lambda: T.row_unpack(e, r, W, a, use_lut=False))
    td2, _ = timeit(lambda: T.row_unpack(e, r, W, a, use_lut=True))
    say(f"| t5row | C OpenMP, div/mod decode | {mbps(len(chunk), te):.0f} | {mbps(len(chunk), td1):.0f} |")
    say(f"| t5row | C OpenMP, LUT decode | {mbps(len(chunk), te):.0f} | {mbps(len(chunk), td2):.0f} |")
    # mixed / t5col
    pres = np.zeros((W, 256), np.uint8)
    fast.analyse(chunk, r, W, pres)
    for label, force in (("mixed", False), ("t5col", True)):
        cls, al, lut = T.pin_classes(pres, force)
        te, e = timeit(lambda: T.mixed_pack_ref(chunk, r, W, cls, lut), 1)
        td, _ = timeit(lambda: T.mixed_unpack_ref(e, r, W, cls, al), 1)
        say(f"| {label} | numpy reference | {mbps(len(chunk), te):.0f} | {mbps(len(chunk), td):.0f} |")
        te, e = timeit(lambda: T.mixed_pack(chunk, r, W, cls, lut))
        td1, _ = timeit(lambda: T.mixed_unpack(e, r, W, cls, al, use_lut=False))
        td2, _ = timeit(lambda: T.mixed_unpack(e, r, W, cls, al, use_lut=True))
        say(f"| {label} | C OpenMP, div/mod decode | {mbps(len(chunk), te):.0f} | {mbps(len(chunk), td1):.0f} |")
        say(f"| {label} | C OpenMP, LUT decode | {mbps(len(chunk), te):.0f} | {mbps(len(chunk), td2):.0f} |")
    base = np.frombuffer(chunk[:W], np.uint8).copy()
    te, e = timeit(lambda: fast.pack(chunk, r, W, base))
    say(f"| bitpack (existing) | C OpenMP | {mbps(len(chunk), te):.0f} | – |")
    say("")


# ------------------------------------------------------------------- part C
def part_c():
    say("## C. t5 stream block size (file 006 first 64 MiB)")
    say("")
    data, W, rows = load("006", 64 << 20)
    n = len(data)
    say("| block | packed only | + zstd L9 | encode MB/s (parallel) |")
    say("|---|---|---|---|")
    with ThreadPoolExecutor(os.cpu_count()) as ex:
        for bs in (4 << 10, 64 << 10, 256 << 10, 1 << 20, 4 << 20, 16 << 20):
            blocks = [data[o:o + bs] for o in range(0, n, bs)]

            def enc_all():
                al = list(ex.map(T.stream_alphabet, blocks))
                return list(ex.map(T.stream_encode, blocks, al))
            t, encs = timeit(enc_all, 2)
            packed = sum(12 + len(e) for e in encs)
            zs = z9(b"".join(bytes(e) for e in encs))
            say(f"| {bs >> 10} KiB | {n / packed:.2f}x | {n / zs:.1f}x | {mbps(n, t):.0f} |")
    say("")


# ------------------------------------------------------------------- part D
def part_d():
    say("## D. Stage timings, file 004 (1.4 GB, W=76, alphabet 01X)")
    say("")
    data, W, rows = load("004")
    n = len(data)
    say("| codec | parse/analyse s | pack s | zstd L9 s | packed MB | final MB | ratio |")
    say("|---|---|---|---|---|---|---|")
    t_an, _ = timeit(lambda: fast.analyse(data, rows, W, np.zeros((W, 256), np.uint8)), 1)
    pres = np.zeros((W, 256), np.uint8)
    fast.analyse(data, rows, W, pres)
    R = 1 << 20
    chunks = [(min(R, rows - r0), data[r0 * (W + 1):(r0 + min(R, rows - r0)) * (W + 1)])
              for r0 in range(0, rows, R)]

    def run(label, pack_fn, t_parse):
        t, parts = timeit(lambda: [pack_fn(b, r) for r, b in chunks], 1)
        packed = b"".join(bytes(p) for p in parts)
        tz, z = timeit(lambda: _compressor(9, -1, True).compress(packed), 1)
        say(f"| {label} | {t_parse:.2f} | {t:.2f} | {tz:.2f} | {len(packed) / 1e6:.0f} | "
            f"{len(z) / 1e6:.1f} | {n / len(z):.1f}x |")

    a = T.stream_alphabet(data[: 1 << 20])
    blocks = [data[o:o + (1 << 20)] for o in range(0, n, 1 << 20)]
    with ThreadPoolExecutor(os.cpu_count()) as ex:
        ta, al = timeit(lambda: list(ex.map(T.stream_alphabet, blocks)), 1)
        t, encs = timeit(lambda: list(ex.map(T.stream_encode, blocks, al)), 1)
    packed = b"".join(bytes(e) for e in encs)
    tz, z = timeit(lambda: _compressor(9, -1, True).compress(packed), 1)
    say(f"| t5 stream | {ta:.2f} (alphabets) | {t:.2f} | {tz:.2f} | {len(packed) / 1e6:.0f} | "
        f"{len(z) / 1e6:.1f} | {n / len(z):.1f}x |")
    syms = np.flatnonzero(pres.any(0))
    alph = np.array(syms[:3], np.uint8)
    run("t5row", lambda b, r: T.row_pack(b, r, W, alph), t_an)
    cls, al, lut = T.pin_classes(pres, True)
    run("t5col", lambda b, r: T.mixed_pack(b, r, W, cls, lut), t_an)
    cls, al, lut = T.pin_classes(pres, False)
    run("mixed", lambda b, r: T.mixed_pack(b, r, W, cls, lut), t_an)
    base = np.frombuffer(data[:W], np.uint8).copy()
    run("bitpack", lambda b, r: fast.pack(b, r, W, base), t_an)
    tz, z = timeit(lambda: _compressor(9, -1, True).compress(data), 1)
    say(f"| plain zstd L9 | – | – | {tz:.2f} | {n / 1e6:.0f} | {len(z) / 1e6:.1f} | {n / len(z):.1f}x |")
    say("")


if __name__ == "__main__":
    say("# Ternary packing – exploration and optimisation")
    say("")
    for part in (part_a, part_b, part_c, part_d):
        part()
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    with open(os.path.join(ROOT, "results", "ternary_explore.md"), "w") as f:
        f.write("\n".join(OUT) + "\n")
    print("\n-> results/ternary_explore.md")
