#!/usr/bin/env python3
"""Measure the ideas of the AMD/EPYC research note on REAL pin streams before
building anything (same rule as tools/explore_v3.py).

    B   back ends on real planes frames (2 MiB groups of unique dense pins):
        zstd 19/22, xz 6/9e, xz with tuned LZMA2 lc/lp/pb, bzip2, bzip3 (BWT),
        brotli 11 (24-bit window)
    F   frame size: 2 / 8 / 32 MiB and whole file (single-core can afford big frames)
    O   pin order: file order vs similarity order (greedy nearest neighbour)
    X   cross-pin XOR: hamming distance of each pin to its nearest other pin

    tools/explore_amd.py --files 003 007 009 014 028 --frames 3
"""
import argparse
import hashlib
import lzma
import os
import sys
import time

import numpy as np
import zstandard as zstd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from patzstd import fast  # noqa: E402
from patzstd.codec import grid_info, members_from_path  # noqa: E402

EXT = os.path.join(ROOT, "data", "extracted")


def load(fid):
    m = next(mm for mm in members_from_path(os.path.join(EXT, fid + ".pat")) if mm.name.endswith(".vec"))
    W, rows, pres, first = grid_info(m)
    base = np.frombuffer(first[:W], np.uint8).copy()
    P = fast.pack(m.view(), rows, W, base).reshape(W, -1)
    seen, uniq = set(), []
    for c in range(W):
        if pres[c].sum() != 2 or not P[c].any():
            continue
        k = hashlib.blake2b(P[c].tobytes()).digest()
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    return W, rows, P, uniq


def xz_raw(b, preset=9 | lzma.PRESET_EXTREME, **kw):
    f = {"id": lzma.FILTER_LZMA2, "preset": preset, **kw}
    return len(lzma.compress(b, format=lzma.FORMAT_RAW, filters=[f]))


def backends():
    import bz2
    import brotli
    import bz3
    z = lambda lvl: (lambda b: len(zstd.ZstdCompressor(level=lvl).compress(b)))  # noqa: E731
    return {
        "zstd19": z(19),
        "zstd22": lambda b: len(zstd.ZstdCompressor(compression_params=zstd.ZstdCompressionParameters.from_level(
            22, source_size=len(b))).compress(b)),
        "xz6": lambda b: xz_raw(b, 6),
        "xz9e": lambda b: xz_raw(b),
        "xz9e_pb0": lambda b: xz_raw(b, pb=0),
        "xz9e_lc0pb0": lambda b: xz_raw(b, lc=0, pb=0),
        "xz9e_lc4pb0": lambda b: xz_raw(b, lc=4, pb=0),
        "xz9e_lc0lp0pb0_n273": lambda b: xz_raw(b, lc=0, lp=0, pb=0, nice_len=273),
        "xz9e_lc1lp0pb0_n273": lambda b: xz_raw(b, lc=1, lp=0, pb=0, nice_len=273),
        "bzip2_9": lambda b: len(bz2.compress(b, 9)),
        "bzip3_16M": lambda b: len(bz3.compress(b, block_size=16 << 20)),
        "brotli11": lambda b: len(brotli.compress(b, quality=11, lgwin=24)),
    }


def frames_of(P, pins, nb, gb):
    per = max(1, gb // nb)
    return [b"".join(P[c].tobytes() for c in pins[i:i + per]) for i in range(0, len(pins), per)]


def exp_backends(fid, P, uniq, nb, nfr, out):
    fr = frames_of(P, uniq, nb, 2 << 20)
    pick = [fr[i] for i in np.linspace(0, len(fr) - 1, min(nfr, len(fr))).astype(int)]
    raw = sum(len(b) for b in pick)
    for name, f in backends().items():
        t = time.perf_counter()
        n = sum(f(b) for b in pick)
        dt = time.perf_counter() - t
        out.append((fid, "B", name, raw, n, dt))
        print(f"  B {fid} {name:22} {raw:>10} -> {n:>9}  {raw / n:6.2f}x  {raw / 1e6 / dt:7.1f} MB/s(packed)", flush=True)


def exp_frames(fid, P, uniq, nb, out, cap=64 << 20):
    pins = uniq[:max(1, cap // nb)]
    for gb in (2 << 20, 8 << 20, 32 << 20, cap):
        fr = frames_of(P, pins, nb, gb)
        raw = sum(len(b) for b in fr)
        for name in ("zstd19", "xz9e_lc0pb0"):
            f = backends()[name]
            t = time.perf_counter()
            n = sum(f(b) for b in fr)
            out.append((fid, f"F{gb >> 20}M", name, raw, n, time.perf_counter() - t))
            print(f"  F {fid} frame {gb >> 20:3} MiB {name:12} {raw:>10} -> {n:>9}  {raw / n:6.2f}x", flush=True)


def order_by_similarity(P, pins):
    """Greedy nearest-neighbour chain by hamming distance on a sample of bytes."""
    s = np.unpackbits(P[pins][:, :: max(1, P.shape[1] // 4096)][:, :4096], axis=1).astype(np.int32)
    left, order = set(range(len(pins))), [0]
    left.remove(0)
    while left:
        cur = s[order[-1]]
        cand = list(left)
        d = np.abs(s[cand] - cur).sum(1)
        j = cand[int(np.argmin(d))]
        order.append(j)
        left.remove(j)
    return [pins[i] for i in order]


def exp_order(fid, P, uniq, nb, out):
    for label, pins in (("file", uniq), ("similar", order_by_similarity(P, uniq))):
        fr = frames_of(P, pins, nb, 2 << 20)
        raw = sum(len(b) for b in fr)
        n = sum(backends()["zstd19"](b) for b in fr)
        out.append((fid, "O", label, raw, n, 0))
        print(f"  O {fid} {label:8} zstd19 {raw:>10} -> {n:>9}  {raw / n:6.2f}x", flush=True)


def exp_xor(fid, P, uniq, nb, out):
    s = np.unpackbits(P[uniq][:, :min(nb, 1 << 16)], axis=1)
    n = s.shape[1]
    best = []
    for i in range(len(uniq)):
        d = (s != s[i]).sum(1)
        d = np.minimum(d, n - d)              # an inverted pin is as good as a copy
        d[i] = n
        best.append(d.min() / n)
    best = np.array(best)
    print(f"  X {fid} nearest-pin hamming: <1% {int((best < .01).sum())}  <5% {int((best < .05).sum())}"
          f"  <20% {int((best < .2).sum())} of {len(uniq)}  median {np.median(best):.3f}", flush=True)
    out.append((fid, "X", "lt5pct", len(uniq), int((best < .05).sum()), 0))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--files", nargs="+", default=["003", "007", "009", "014", "028"])
    ap.add_argument("--frames", type=int, default=3, help="2 MiB frames sampled per file for B")
    ap.add_argument("--exp", nargs="+", default=["B", "F", "O", "X"])
    a = ap.parse_args()
    fast.set_threads(os.cpu_count())
    out = []
    for fid in a.files:
        W, rows, P, uniq = load(fid)
        nb = P.shape[1]
        print(f"{fid}: W={W} rows={rows} unique dense pins={len(uniq)} ({nb} B each)", flush=True)
        if "B" in a.exp:
            exp_backends(fid, P, uniq, nb, a.frames, out)
        if "F" in a.exp:
            exp_frames(fid, P, uniq, nb, out)
        if "O" in a.exp:
            exp_order(fid, P, uniq, nb, out)
        if "X" in a.exp:
            exp_xor(fid, P, uniq, nb, out)
    path = os.path.join(ROOT, "results", f"explore_amd_{time.strftime('%Y%m%d_%H%M%S')}.csv")
    with open(path, "w") as f:
        f.write("file,exp,variant,raw_bytes,comp_bytes,seconds\n")
        for r in out:
            f.write(",".join(str(x) for x in r) + "\n")
    print("->", path)


if __name__ == "__main__":
    main()
