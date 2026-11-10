#!/usr/bin/env python3
"""Quick experiments that decide which ideas from the bit-plane report are
worth building (run after tools/recon.py). All on unique-pin bit streams.

    E4  pin dedup               unique pins only vs all pins (chunked layout)
    E7  cross-file sharing      identical pin streams / blocks across files
    E7b long window             zstd windowLog 27 vs 31 (+LDM)
    E8  back end                zstd L19 vs xz/LZMA -9e
    C   chunk length            1 Mi rows vs whole file per pin

    tools/explore_v3.py --files 003 008 009 028
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
        if pres[c].sum() < 2:
            continue
        k = hashlib.blake2b(P[c].tobytes()).digest()
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    return W, rows, P, uniq


def zs(b, level, wlog=27, ldm=True, threads=-1):
    p = zstd.ZstdCompressionParameters.from_level(level, window_log=wlog, enable_ldm=ldm, threads=threads)
    t = time.perf_counter()
    n = len(zstd.ZstdCompressor(compression_params=p).compress(b))
    return n, time.perf_counter() - t


def chunked(P, rows, pins, R=1 << 20):
    nb = P.shape[1]
    parts = []
    for b0 in range(0, nb, R // 8):
        parts.append(np.ascontiguousarray(P[pins, b0:b0 + R // 8]).tobytes())
    return b"".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", nargs="+", default=["003", "008", "009", "028"])
    ap.add_argument("--xz", action="store_true", help="also run xz -9e (slow)")
    a = ap.parse_args()
    data = {}
    for fid in a.files:
        W, rows, P, uniq = load(fid)
        data[fid] = (rows, P, uniq)
        allp = [c for c in range(W) if P[c].any()] if len(uniq) < W else list(range(W))
        s_all = chunked(P, rows, list(range(W)))
        s_uni = chunked(P, rows, uniq)
        s_whole = np.ascontiguousarray(P[uniq]).tobytes()
        print(f"\n== {fid}: W={W} unique={len(uniq)} rows={rows:,}  packed all={len(s_all):,} unique={len(s_uni):,}")
        for lvl in (3, 9, 19):
            for name, s in (("all pins, 1Mi chunks", s_all), ("unique, 1Mi chunks", s_uni),
                            ("unique, whole-file pin", s_whole)):
                if lvl == 19 and name == "all pins, 1Mi chunks":
                    continue
                n, t = zs(s, lvl)
                print(f"  L{lvl:<2} {name:24} {n:>12,} B  {len(s) / 1e6 / t:7.0f} MB/s in")
        for wl in (30, 31):
            n, t = zs(s_uni, 19, wlog=wl)
            print(f"  L19 unique chunks wlog={wl}      {n:>12,} B  {len(s_uni) / 1e6 / t:7.0f} MB/s in")
        if a.xz:
            t = time.perf_counter()
            n = len(lzma.compress(s_uni, preset=9 | lzma.PRESET_EXTREME))
            print(f"  xz -9e unique chunks           {n:>12,} B  {len(s_uni) / 1e6 / (time.perf_counter() - t):7.1f} MB/s in")

    # cross-file: identical unique pin streams and identical 64 KiB blocks
    print("\n== cross-file sharing")
    pin_owner, blk_owner = {}, {}
    for fid, (rows, P, uniq) in data.items():
        same_pin = same_blk = nblk = 0
        for c in uniq:
            k = hashlib.blake2b(P[c].tobytes()).digest()
            same_pin += k in pin_owner
            pin_owner.setdefault(k, fid)
            x = P[c]
            for o in range(0, len(x) - 65535, 65536):
                kb = hashlib.blake2b(x[o:o + 65536].tobytes(), digest_size=16).digest()
                nblk += 1
                if kb in blk_owner and blk_owner[kb] != fid:
                    same_blk += 1
                blk_owner.setdefault(kb, fid)
        print(f"  {fid}: unique pins also seen in an earlier file: {same_pin}/{len(uniq)}; "
              f"64 KiB pin blocks seen in an earlier file: {same_blk}/{nblk}")
    if len(data) > 1:
        solo = sum(zs(chunked(P, r, u), 9)[0] for r, P, u in data.values())
        cat = b"".join(chunked(P, r, u) for r, P, u in data.values())
        n, _ = zs(cat, 9, wlog=31)
        print(f"  L9 separate files {solo:,} B  vs  one solid stream (wlog 31) {n:,} B  ({100 * (n / solo - 1):+.2f}%)")


if __name__ == "__main__":
    main()
