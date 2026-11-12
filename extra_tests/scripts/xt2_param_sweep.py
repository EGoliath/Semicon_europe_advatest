#!/usr/bin/env python3
"""zstd parameter sweep on the bk container frames (bk16:19l), sizes only + verify."""
import os, sys, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import xt2codec as xc
DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "extracted")
# (name, minMatch, targetLength, searchLog, strategy, chainLog, hashLog); strategy 9 = btultra2
VARIANTS = [("L19 default", 0, 0, 0, 0, 0, 0), ("mm3", 3, 0, 0, 0, 0, 0), ("mm4", 4, 0, 0, 0, 0, 0),
            ("mm5", 5, 0, 0, 0, 0, 0), ("mm6", 6, 0, 0, 0, 0, 0), ("tl999", 0, 999, 0, 0, 0, 0),
            ("btultra2", 0, 0, 0, 9, 0, 0), ("sl9 cl27 hl26", 0, 0, 9, 0, 27, 26),
            ("btultra2 tl999 sl9", 0, 999, 9, 9, 0, 0)]
spec = xc.parse(sys.argv[1] if len(sys.argv) > 1 else "bk16:19l")
files = sys.argv[2:] or ["007", "014", "004"]
tot = {v[0]: [0, 0.0] for v in VARIANTS}
for fid in files:
    buf = np.fromfile(os.path.join(DATA, f"{fid}.pat", "Vectors.vec"), np.uint8)
    g = xc.Grid(buf)
    for v in VARIANTS:
        xc.L.xt2_set_params(*v[1:])
        t0 = time.perf_counter(); pk = xc.compress(spec, buf, g); tc = time.perf_counter() - t0
        ok = xc.equal(xc.decompress(pk, len(buf)), buf)
        tot[v[0]][0] += pk.size; tot[v[0]][1] += tc
        print(f"{fid} {v[0]:22} {pk.size:12,} {len(buf)/1e6/tc:7.0f} MB/s {'OK' if ok else 'FAIL'}", flush=True)
    del buf
base = tot["L19 default"][0]
print("\nTOTAL", files)
for k, (s, t) in sorted(tot.items(), key=lambda x: x[1][0]):
    print(f"{k:22} {s:12,} {100*(s/base-1):+6.2f}%  {t:6.1f} s")
