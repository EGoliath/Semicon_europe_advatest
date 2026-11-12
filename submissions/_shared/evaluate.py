#!/usr/bin/env python3
"""Evaluate this codec package: compress + decompress every .pat file, verify the
round trip with SHA-256 against the source, and report size and speed.

    python evaluate.py /path/to/pat_files/              # every *.pat in the folder
    python evaluate.py 001.pat 006.pat                  # selected files
    python evaluate.py /path/to/extracted/ --extracted  # folders NNN.pat/ with the members
    python evaluate.py DATA -- -l 9                     # extra args go to compress.py

Times are wall clock of the package's own compress.py / decompress.py (including
Python start-up and file I/O). Results -> eval_<package>_<timestamp>.csv / .md
"""
import argparse
import csv
import glob
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.basename(HERE)


def sha_members(path):
    out = {}
    if os.path.isdir(path):
        for n in sorted(os.listdir(path)):
            p = os.path.join(path, n)
            if os.path.isfile(p):
                h = hashlib.sha256()
                with open(p, "rb") as f:
                    for b in iter(lambda: f.read(16 << 20), b""):
                        h.update(b)
                out[n] = (os.path.getsize(p), h.hexdigest())
        return out
    with zipfile.ZipFile(path) as z:
        for i in z.infolist():
            if i.is_dir():
                continue
            h = hashlib.sha256()
            with z.open(i) as f:
                for b in iter(lambda: f.read(16 << 20), b""):
                    h.update(b)
            out[i.filename] = (i.file_size, h.hexdigest())
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help=".pat files, or folders containing them")
    ap.add_argument("--extracted", action="store_true", help="inputs are extracted NNN.pat/ folders")
    ap.add_argument("--work", default=None, help="scratch folder (default: system temp)")
    ap.add_argument("--keep", action="store_true", help="keep compressed files")
    argv = sys.argv[1:]
    cut = argv.index("--") if "--" in argv else len(argv)
    a = ap.parse_args(argv[:cut])
    extra = argv[cut + 1:]  # everything after -- goes to compress.py

    files = []
    for p in a.inputs:
        if os.path.isdir(p) and not (a.extracted and p.rstrip("/").endswith(".pat")):
            files += sorted(glob.glob(os.path.join(p, "*.pat")))
        else:
            files.append(p)
    work = tempfile.mkdtemp(prefix=f"eval_{PKG}_", dir=a.work)
    py = sys.executable
    rows = []
    print(f"{PKG}: {len(files)} files, compress.py args {extra or '(defaults)'}")
    print(f"{'file':10} {'original':>14} {'compressed':>14} {'ratio':>7} {'comp s':>8} {'MB/s':>7} "
          f"{'decomp s':>8} {'MB/s':>7}  verified")
    try:
        for src in files:
            ref = sha_members(src)
            orig = sum(s for s, _ in ref.values())
            cdir, rdir = os.path.join(work, "c"), os.path.join(work, "r")
            os.makedirs(cdir, exist_ok=True)
            t0 = time.perf_counter()
            subprocess.run([py, os.path.join(HERE, "compress.py"), src, "-o", cdir, *extra],
                           check=True, stdout=subprocess.DEVNULL)
            tc = time.perf_counter() - t0
            (comp_file,) = [os.path.join(cdir, f) for f in os.listdir(cdir)]
            csize = os.path.getsize(comp_file)
            t0 = time.perf_counter()
            subprocess.run([py, os.path.join(HERE, "decompress.py"), comp_file, "-o", rdir],
                           check=True, stdout=subprocess.DEVNULL)
            td = time.perf_counter() - t0
            (out_dir,) = [os.path.join(rdir, f) for f in os.listdir(rdir)]
            ok = sha_members(out_dir) == ref
            name = os.path.basename(src.rstrip("/"))
            rows.append(dict(file=name, original=orig, compressed=csize, ratio=orig / csize,
                             comp_s=tc, decomp_s=td, verified=int(ok)))
            print(f"{name:10} {orig:14,} {csize:14,} {orig / csize:6.1f}x {tc:8.2f} {orig / 1e6 / tc:7.0f} "
                  f"{td:8.2f} {orig / 1e6 / td:7.0f}  {'OK' if ok else 'FAIL'}", flush=True)
            if a.keep:
                shutil.move(comp_file, os.path.join(HERE, os.path.basename(comp_file)))
            shutil.rmtree(cdir); shutil.rmtree(rdir)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if not rows:
        return
    O = sum(r["original"] for r in rows); C = sum(r["compressed"] for r in rows)
    TC = sum(r["comp_s"] for r in rows); TD = sum(r["decomp_s"] for r in rows)
    V = sum(r["verified"] for r in rows)
    print(f"\nTOTAL {O / 1e6:.1f} MB -> {C / 1e6:.1f} MB  ratio {O / C:.2f}x  "
          f"compress {O / 1e6 / TC:.0f} MB/s  decompress {O / 1e6 / TD:.0f} MB/s  verified {V}/{len(rows)}")
    base = os.path.join(os.getcwd(), f"eval_{PKG}_{time.strftime('%Y%m%d_%H%M%S')}")
    with open(base + ".csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    with open(base + ".md", "w") as f:
        f.write(f"# {PKG} evaluation\n\ncompress.py args: `{' '.join(extra) or 'defaults'}`\n\n"
                "| files | original | compressed | ratio | comp MB/s | decomp MB/s | verified |\n"
                "|---|---|---|---|---|---|---|\n"
                f"| {len(rows)} | {O / 1e6:.1f} MB | {C / 1e6:.1f} MB | {O / C:.2f}x | {O / 1e6 / TC:.0f} | "
                f"{O / 1e6 / TD:.0f} | {V}/{len(rows)} |\n")
    print("results:", base + ".md")
    sys.exit(0 if V == len(rows) else 1)


if __name__ == "__main__":
    main()
