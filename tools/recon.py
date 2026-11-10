#!/usr/bin/env python3
"""E0 corpus reconnaissance: where do the compressed bytes actually live?

For every Vectors.vec in data/extracted, pack each pin into its own bit
stream (1 bit / vector, the same layout as the bitpack mode) and measure per pin:

    class       const | dup (identical to an earlier pin) | inv (complement of
                an earlier pin) | periodic | slow | dense
    toggles     number of value changes
    h1_bytes    order-1 (Markov) entropy floor = rows * H_b(toggle rate) / 8
    zstd_bytes  zstd L9 size of the pin stream alone
    period      best lag (2..2^19) by autocorrelation on a 1 Mi-bit sample
    match       fraction of bits equal at that lag (sample)
    pxor_bytes  zstd L9 size after period-aligned XOR (x[t] ^= x[t-period])

Only pins that use >= 2 symbols are packed; 3-symbol pins (H/L/X, files 001
and 015 only, 36 KB total) are reported as class 'ternary' and skipped.

    tools/recon.py                  # whole corpus -> results/recon_pins.csv + recon.md
    tools/recon.py --files 006 007
"""
import argparse
import csv
import glob
import hashlib
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import zstandard as zstd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from patzstd import fast  # noqa: E402
from patzstd.codec import grid_info, members_from_path  # noqa: E402

POP = np.array([bin(i).count("1") for i in range(256)], np.int64)
SAMPLE = 1 << 20


def hb(p):
    p = np.clip(p, 1e-300, 1 - 1e-16)
    return np.where((p <= 1e-300) | (p >= 1), 0.0, -(p * np.log2(p) + (1 - p) * np.log2(1 - p)))


def zsize(b, level=9):
    return len(zstd.ZstdCompressor(level=level).compress(bytes(b)))


def toggles(x, rows):
    prev = np.empty_like(x)
    prev[0] = x[0] >> 7 << 7                                   # bit 0 has no predecessor: copy it
    prev[1:] = (x[:-1] & 1) << 7
    y = (x >> 1) | prev
    if 0 < rows % 8:                                           # ignore padding bits
        y[-1] &= (0xFF << (8 - rows % 8)) & 0xFF
        d = (x ^ y)
        d[-1] &= (0xFF << (8 - rows % 8)) & 0xFF
        return int(POP[d].sum())
    return int(POP[x ^ y].sum())


def best_period(x, rows):
    n = min(rows, SAMPLE)
    bits = np.unpackbits(x[: (n + 7) // 8], count=n).astype(np.float64) * 2 - 1
    f = np.fft.rfft(bits, 2 * n)
    ac = np.fft.irfft(f * np.conj(f))[: n // 2]
    ac[:2] = -np.inf
    lag = int(np.argmax(ac))
    match = float((ac[lag] / (n - lag) + 1) / 2)
    return lag, match


def shift_xor(x, rows, p):
    bits = np.unpackbits(x, count=rows)
    out = bits.copy()
    out[p:] ^= bits[:-p]
    return np.packbits(out)


def analyse_file(fid, extracted):
    folder = os.path.join(extracted, fid + ".pat")
    m = next(mm for mm in members_from_path(folder) if mm.name.endswith(".vec"))
    W, rows, pres, first = grid_info(m)
    nsym = pres.sum(1)
    base = np.frombuffer(first[:W], np.uint8).copy()
    view = m.view()
    packed = fast.pack(view, rows, W, base).reshape(W, -1) if nsym.max() <= 2 else None
    nb = (rows + 7) // 8
    seen, out = {}, []
    tail = (0xFF << (8 - rows % 8)) & 0xFF if rows % 8 else 0xFF
    jobs = []
    for c in range(W):
        syms = "".join(chr(s) for s in np.flatnonzero(pres[c]))
        r = {"file": fid, "pin": c, "symbols": syms, "rows": rows}
        if nsym[c] == 1:
            r.update(cls="const", toggles=0, h1_bytes=0.0, zstd_bytes=0)
        elif nsym[c] == 3 or packed is None:
            r.update(cls="ternary")
        else:
            x = packed[c]
            inv = ~x
            inv[-1] &= tail
            k, ki = hashlib.blake2b(x.tobytes()).digest(), hashlib.blake2b(inv.tobytes()).digest()
            if k in seen:
                r.update(cls="dup", ref=seen[k])
            elif ki in seen:
                r.update(cls="inv", ref=seen[ki])
            else:
                seen[k] = c
                jobs.append((r, x))
        out.append(r)

    def work(job):
        r, x = job
        t = toggles(x, rows)
        p = t / max(rows - 1, 1)
        r["toggles"] = t
        r["h1_bytes"] = float(rows * hb(p) / 8)
        r["zstd_bytes"] = zsize(x)
        if t > 2:
            lag, match = best_period(x, rows)
            r["period"], r["match"] = lag, round(match, 4)
            if match > 0.6:
                r["pxor_bytes"] = zsize(shift_xor(x, rows, lag))
        rate = t / rows
        if r.get("match", 0) > 0.999:
            r["cls"] = "periodic"
        elif rate < 0.01:
            r["cls"] = "slow"
        else:
            r["cls"] = "dense"
        return r

    with ThreadPoolExecutor(os.cpu_count()) as ex:
        list(ex.map(work, jobs))
    whole = zsize(packed.reshape(-1)) if packed is not None else None
    return W, rows, out, whole, nb


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--files", nargs="*")
    ap.add_argument("--extracted", default=os.path.join(ROOT, "data", "extracted"))
    a = ap.parse_args()
    fids = sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(a.extracted, "*.pat"))
                  if os.path.isdir(p))
    if a.files:
        fids = [f for f in fids if f in a.files]
    fields = ["file", "pin", "symbols", "rows", "cls", "ref", "toggles", "h1_bytes", "zstd_bytes",
              "period", "match", "pxor_bytes"]
    allrows, summ = [], []
    for fid in fids:
        W, rows, pins, whole, nb = analyse_file(fid, a.extracted)
        allrows += pins
        by = {}
        for r in pins:
            d = by.setdefault(r["cls"], [0, 0, 0.0, 0])
            d[0] += 1
            d[1] += r.get("zstd_bytes", 0) or 0
            d[2] += r.get("h1_bytes", 0) or 0
            d[3] += min(r.get("zstd_bytes", 0) or 0, r.get("pxor_bytes", 1 << 62))
        per_pin = sum(v[1] for v in by.values())
        summ.append((fid, W, rows, whole, per_pin, by))
        cls_s = " ".join(f"{k}:{v[0]}" for k, v in sorted(by.items()))
        print(f"{fid} W={W:3} rows={rows:>9}  packed-all zstd={whole}  per-pin zstd={per_pin}  "
              f"floor(h1)={sum(v[2] for v in by.values()):.0f}  [{cls_s}]", flush=True)

    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    with open(os.path.join(ROOT, "results", "recon_pins.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(allrows)

    tot = {}
    for *_, by in summ:
        for k, v in by.items():
            t = tot.setdefault(k, [0, 0, 0.0, 0])
            for i in range(4):
                t[i] += v[i]
    md = ["# E0 corpus reconnaissance (tools/recon.py)", "",
          "Per-pin bit streams (1 bit/vector), each compressed alone with zstd L9.", "",
          "## Where the bytes live (whole corpus)", "",
          "| pin class | pins | zstd bytes | share | order-1 floor | best of zstd / period-XOR |",
          "|---|---|---|---|---|---|"]
    allz = sum(t[1] for t in tot.values())
    for k, t in sorted(tot.items(), key=lambda kv: -kv[1][1]):
        md.append(f"| {k} | {t[0]} | {t[1]:,} | {100 * t[1] / max(allz, 1):.1f}% | {t[2]:,.0f} | {t[3]:,} |")
    md += ["", "## Per file", "",
           "| file | pins | rows | packed stream zstd L9 | sum of per-pin zstd | order-1 floor | classes |",
           "|---|---|---|---|---|---|---|"]
    for fid, W, rows, whole, per_pin, by in summ:
        cls_s = ", ".join(f"{k} {v[0]}" for k, v in sorted(by.items()))
        md.append(f"| {fid} | {W} | {rows:,} | {whole if whole is None else f'{whole:,}'} | {per_pin:,} | "
                  f"{sum(v[2] for v in by.values()):,.0f} | {cls_s} |")
    with open(os.path.join(ROOT, "results", "recon.md"), "w") as f:
        f.write("\n".join(md) + "\n")
    print("\n".join(md[:12 + len(tot)]))


if __name__ == "__main__":
    main()
