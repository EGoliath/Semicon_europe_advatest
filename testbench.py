#!/usr/bin/env python3
"""Test bench: compress + decompress every pattern, verify it is bit-exact,
and report compression ratio and speed for each configuration.

    ./testbench.py                                  # all files, default configs
    ./testbench.py --files 001 006 007              # subset
    ./testbench.py --configs raw:3 auto:3 auto:19   # mode:level pairs
    ./testbench.py --quick                          # only files < 50 MB packed

Verification is independent of the codec's own checksums: the SHA-256 of every
original member is computed straight from the source .pat, then compared
with the SHA-256 of the decompressed stream (and the byte counts must match).
Results -> results/bench_<timestamp>.csv and .md
"""
import argparse
import csv
import glob
import hashlib
import os
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from patzstd import compress  # noqa: E402
from patzstd.codec import iter_members  # noqa: E402

DEFAULT_CONFIGS = ["raw:3", "raw:19", "auto:3", "auto:19"]


class HashSink:
    def __init__(self):
        self.h, self.n = hashlib.sha256(), 0

    def write(self, b):
        self.h.update(b)
        self.n += len(b)


def source_digests(pat, folder=None):
    """sha256 of every original member, read straight from the source."""
    out = {}
    if folder:
        for n in sorted(os.listdir(folder)):
            h = hashlib.sha256()
            with open(os.path.join(folder, n), "rb") as f:
                for b in iter(lambda: f.read(8 << 20), b""):
                    h.update(b)
            out[n] = (os.path.getsize(os.path.join(folder, n)), h.hexdigest())
        return out
    with zipfile.ZipFile(pat) as z:
        for i in z.infolist():
            h = hashlib.sha256()
            with z.open(i) as f:
                for b in iter(lambda: f.read(8 << 20), b""):
                    h.update(b)
            out[i.filename] = (i.file_size, h.hexdigest())
    return out


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.1f} {u}" if u != "B" else f"{n} B"
        n /= 1024


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=os.path.join(ROOT, "data", "pat_original"))
    ap.add_argument("--files", nargs="*", help="ids like 001 007 (default: all)")
    ap.add_argument("--configs", nargs="*", default=DEFAULT_CONFIGS,
                    help="mode:level; mode in auto|raw|transpose|bitpack|t5|t5row|t5col|mixed; level 1-22 or none (= packing only, no zstd)")
    ap.add_argument("--source", choices=["extracted", "pat"], default="extracted",
                    help="compress from extracted folders (default) or straight from .pat zips")
    ap.add_argument("--extracted", default=os.path.join(ROOT, "data", "extracted"))
    ap.add_argument("--threads", type=int, default=-1, help="worker threads (-1 = all)")
    ap.add_argument("--tag", default="", help="label added to the result file name")
    ap.add_argument("--quick", action="store_true", help="skip .pat files > 50 MB")
    ap.add_argument("--workdir", default=os.path.join(ROOT, "work"))
    ap.add_argument("--keep", action="store_true", help="keep the .pzst outputs")
    a = ap.parse_args()

    pats = sorted(glob.glob(os.path.join(a.data, "*.pat")))
    if a.files:
        want = {f.replace(".pat", "") for f in a.files}
        pats = [p for p in pats if os.path.basename(p)[:-4] in want]
    if a.quick:
        pats = [p for p in pats if os.path.getsize(p) < 50e6]
    if not pats:
        sys.exit("no input files")
    def parse(c):
        mode, lvl = c.split(":")
        return mode, None if lvl == "none" else int(lvl)
    configs = [parse(c) for c in a.configs]

    os.makedirs(a.workdir, exist_ok=True)
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    tag = f"_{a.tag}" if a.tag else ""
    csv_path = os.path.join(ROOT, "results", f"bench_{stamp}{tag}.csv")
    fields = ["file", "source", "threads", "config", "vec_mode", "orig_bytes", "pat_zip_bytes", "pzst_bytes",
              "ratio", "vs_zip", "comp_s", "comp_MBps", "decomp_s", "decomp_MBps", "verified"]
    rows, failures = [], 0

    print(f"{len(pats)} files x {len(configs)} configs\n")
    print(f"{'file':5} {'config':12} {'mode':9} {'original':>10} {'pzst':>10} "
          f"{'ratio':>8} {'vs zip':>7} {'comp MB/s':>9} {'dec MB/s':>9}  ok")
    with open(csv_path, "w", newline="") as fcsv:
        wr = csv.DictWriter(fcsv, fieldnames=fields)
        wr.writeheader()
        for pat in pats:
            fid = os.path.basename(pat)[:-4]
            folder = os.path.join(a.extracted, fid + ".pat")
            src = folder if a.source == "extracted" else pat
            if a.source == "extracted" and not os.path.isdir(folder):
                sys.exit(f"missing {folder}")
            ref = source_digests(pat, folder if a.source == "extracted" else None)
            orig = sum(s for s, _ in ref.values())
            zbytes = os.path.getsize(pat)
            for mode, level in configs:
                cfg = f"{mode}:{'none' if level is None else level}"
                dst = os.path.join(a.workdir, f"{fid}_{mode}{level}.pzst")
                t0 = time.perf_counter()
                rep = compress(src, dst, level=level, threads=a.threads,
                               force_mode=None if mode == "auto" else mode)
                tc = time.perf_counter() - t0
                size = os.path.getsize(dst)

                t0 = time.perf_counter()
                ok, got = True, {}
                try:
                    for name, _, _, emit in iter_members(dst, a.threads):
                        s = HashSink()
                        emit(s)
                        got[name] = (s.n, s.h.hexdigest())
                except Exception as e:           # integrity failure
                    ok = False
                    print(f"  ERROR {fid} {cfg}: {e}")
                td = time.perf_counter() - t0
                ok = ok and got == ref
                failures += not ok
                if not a.keep:
                    os.remove(dst)

                vmode = next((m["mode"] for m in rep if m["name"].endswith(".vec")), "-")
                r = {"file": fid, "source": a.source, "threads": a.threads, "config": cfg, "vec_mode": vmode,
                     "orig_bytes": orig, "pat_zip_bytes": zbytes, "pzst_bytes": size,
                     "ratio": round(orig / size, 2), "vs_zip": round(zbytes / size, 2),
                     "comp_s": round(tc, 3), "comp_MBps": round(orig / 1e6 / tc, 1),
                     "decomp_s": round(td, 3), "decomp_MBps": round(orig / 1e6 / td, 1),
                     "verified": "PASS" if ok else "FAIL"}
                wr.writerow(r)
                fcsv.flush()
                rows.append(r)
                print(f"{fid:5} {cfg:12} {vmode:9} {human(orig):>10} {human(size):>10} "
                      f"{r['ratio']:>7.1f}x {r['vs_zip']:>6.1f}x {r['comp_MBps']:>9.0f} "
                      f"{r['decomp_MBps']:>9.0f}  {r['verified']}", flush=True)

    # ---- summary
    md = [f"# Pattern zstd benchmark ({stamp}{tag})", "",
          f"{len(pats)} files, source: `{a.source}`, threads: {a.threads}", "",
          "| config | files | original | compressed | ratio | vs .pat zip | "
          "comp MB/s | decomp MB/s | verified |",
          "|---|---|---|---|---|---|---|---|---|"]
    print("\nSUMMARY (totals over all files)")
    for mode, level in configs:
        cfg = f"{mode}:{'none' if level is None else level}"
        rs = [r for r in rows if r["config"] == cfg]
        o = sum(r["orig_bytes"] for r in rs)
        c = sum(r["pzst_bytes"] for r in rs)
        z = sum(r["pat_zip_bytes"] for r in rs)
        tc = sum(r["comp_s"] for r in rs)
        td = sum(r["decomp_s"] for r in rs)
        npass = sum(r["verified"] == "PASS" for r in rs)
        line = (f"| {cfg} | {len(rs)} | {human(o)} | {human(c)} | {o / c:.1f}x | "
                f"{z / c:.1f}x | {o / 1e6 / tc:.0f} | {o / 1e6 / td:.0f} | {npass}/{len(rs)} |")
        md.append(line)
        print(f"  {cfg:10} {human(o):>10} -> {human(c):>10}  ratio {o / c:6.1f}x  "
              f"vs zip {z / c:5.1f}x  comp {o / 1e6 / tc:6.0f} MB/s  "
              f"decomp {o / 1e6 / td:6.0f} MB/s  verified {npass}/{len(rs)}")
    md_path = csv_path[:-4] + ".md"
    with open(md_path, "w") as f:
        f.write("\n".join(md) + "\n")
    print(f"\nCSV: {csv_path}\nMD : {md_path}")
    if failures:
        print(f"\n{failures} FAILURES")
        sys.exit(1)
    print("\nALL ROUND-TRIPS BIT-EXACT")


if __name__ == "__main__":
    main()
