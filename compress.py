#!/usr/bin/env python3
"""Compress .pat files (or extracted .pat folders) to .pzst using zstd.

    ./compress.py data/pat_original/001.pat                  -> out/001.pzst
    ./compress.py data/extracted/*.pat -o out -l 19
    ./compress.py data/pat_original/003.pat --mode raw       # plain zstd baseline
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patzstd import compress  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help=".pat file(s) or extracted folder(s)")
    ap.add_argument("-o", "--outdir", default="out")
    ap.add_argument("-l", "--level", default="3",
                    help="zstd level 1-22 (default 3), or none = packing only")
    ap.add_argument("-T", "--threads", type=int, default=-1, help="-1 = all cores")
    ap.add_argument("--mode", default="auto",
                    choices=["auto", "raw", "transpose", "bitpack", "t5", "t5row", "t5col", "mixed", "best"])
    ap.add_argument("--no-long", action="store_true", help="disable long-distance matching")
    a = ap.parse_args()

    os.makedirs(a.outdir, exist_ok=True)
    for src in a.inputs:
        base = os.path.basename(src.rstrip("/"))
        stem = base[:-4] if base.endswith(".pat") else base
        dst = os.path.join(a.outdir, stem + ".pzst")
        t0 = time.perf_counter()
        rep = compress(src, dst, level=None if a.level == "none" else int(a.level),
                       threads=a.threads,
                       long_distance=not a.no_long,
                       force_mode=None if a.mode == "auto" else a.mode)
        dt = time.perf_counter() - t0
        orig = sum(m["size"] for m in rep)
        comp = os.path.getsize(dst)
        modes = ",".join(f'{m["name"]}:{m["mode"]}' for m in rep)
        print(f"{src} -> {dst}  {orig:,} -> {comp:,} B  ratio {orig / comp:.1f}x  "
              f"{dt:.2f}s  [{modes}]")


if __name__ == "__main__":
    main()
