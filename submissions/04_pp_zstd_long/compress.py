#!/usr/bin/env python3
"""Compress .pat files (or extracted NNN.pat/ folders) with this package's codec.

    python compress.py 001.pat 006.pat -o out          -> out/001.pxt, out/006.pxt
    python compress.py data/extracted/*.pat -o out -l 9
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codec  # noqa: E402
import patio  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=(codec.__doc__ or "") + "\n" + __doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help=".pat file(s) or extracted folder(s)")
    ap.add_argument("-o", "--outdir", default="out")
    ap.add_argument("-l", "--level", type=int, default=codec.DEFAULT_LEVEL,
                    help=f"zstd level (default {codec.DEFAULT_LEVEL})")
    ap.add_argument("-T", "--threads", type=int, default=0, help="0 = all cores")
    for flag, kw in getattr(codec, "EXTRA_ARGS", []):
        ap.add_argument(flag, **kw)
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    extra = {k: v for k, v in vars(a).items() if k not in ("inputs", "outdir", "level", "threads")}
    for src in a.inputs:
        dst = os.path.join(a.outdir, patio.stem_of(src) + ".pxt")
        t0 = time.perf_counter()
        codec.compress(src, dst, level=a.level, threads=a.threads, **extra)
        dt = time.perf_counter() - t0
        orig = (sum(os.path.getsize(os.path.join(src, n)) for n in os.listdir(src))
                if os.path.isdir(src) else None)
        comp = os.path.getsize(dst)
        ratio = f"  ratio {orig / comp:.1f}x" if orig else ""
        print(f"{src} -> {dst}  {comp:,} B{ratio}  {dt:.2f}s", flush=True)


if __name__ == "__main__":
    main()
