#!/usr/bin/env python3
"""Decompress .pzst files back to the original pattern members.

    ./decompress.py out/001.pzst                 -> restored/001.pat/{Program.sprg,...}
    ./decompress.py out/*.pzst --as-pat          -> restored/001.pat (zip archive)

Every member is checked against the SHA-256 stored at compression time.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patzstd import decompress  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("-o", "--outdir", default="restored")
    ap.add_argument("--as-pat", action="store_true",
                    help="write a .pat zip archive instead of a folder")
    a = ap.parse_args()

    os.makedirs(a.outdir, exist_ok=True)
    for src in a.inputs:
        stem = os.path.basename(src)
        stem = stem[:-5] if stem.endswith(".pzst") else stem
        dst = os.path.join(a.outdir, stem + ".pat")
        t0 = time.perf_counter()
        decompress(src, dst, as_pat=a.as_pat)
        print(f"{src} -> {dst}  {time.perf_counter() - t0:.2f}s  (checksum OK)")


if __name__ == "__main__":
    main()
