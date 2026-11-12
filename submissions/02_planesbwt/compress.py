#!/usr/bin/env python3
"""planesbwt: per-pin bit planes + bzip3 (BWT) frames.

    python compress.py 001.pat 006.pat -o out          -> out/001.pzst, out/006.pzst
    python compress.py data/extracted/*.pat -o out -l 1

Fixed mode: amd_planesbwt_mt (level = -l, default 1). Library: ./patamd (copy of the repo's patamd/).
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patamd import compress  # noqa: E402

MODE, DEFAULT_LEVEL = "amd_planesbwt_mt", 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help=".pat file(s) or extracted folder(s)")
    ap.add_argument("-o", "--outdir", default="out")
    ap.add_argument("-l", "--level", type=int, default=DEFAULT_LEVEL)
    ap.add_argument("-T", "--threads", type=int, default=-1, help="-1 = all cores")
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    for src in a.inputs:
        base = os.path.basename(src.rstrip("/"))
        dst = os.path.join(a.outdir, (base[:-4] if base.endswith(".pat") else base) + ".pzst")
        t0 = time.perf_counter()
        rep = compress(src, dst, level=a.level, threads=a.threads, force_mode=MODE)
        orig, comp = sum(m["size"] for m in rep), os.path.getsize(dst)
        print(f"{src} -> {dst}  {orig:,} -> {comp:,} B  ratio {orig / comp:.1f}x  "
              f"{time.perf_counter() - t0:.2f}s", flush=True)


if __name__ == "__main__":
    main()
