#!/usr/bin/env python3
"""Decompress .pxt files back to the original pattern members.

    python decompress.py out/001.pxt -o restored            -> restored/001.pat/{Program.sprg,...}
    python decompress.py out/*.pxt -o restored --as-pat     -> restored/001.pat (zip archive)

Every member is checked against the xxh3-128 stored at compression time.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codec  # noqa: E402
import patio  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("-o", "--outdir", default="restored")
    ap.add_argument("--as-pat", action="store_true", help="write a .pat zip archive instead of a folder")
    ap.add_argument("-T", "--threads", type=int, default=0, help="0 = all cores")
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    for src in a.inputs:
        dst = os.path.join(a.outdir, patio.stem_of(src) + ".pat")
        t0 = time.perf_counter()
        patio.write_members(dst, codec.iter_decompress(src, a.threads), as_pat=a.as_pat)
        print(f"{src} -> {dst}  {time.perf_counter() - t0:.2f}s  (checksum OK)", flush=True)


if __name__ == "__main__":
    main()
