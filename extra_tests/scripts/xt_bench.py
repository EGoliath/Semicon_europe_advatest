#!/usr/bin/env python3
"""Bench for the extra_tests `xt` codecs against plain zstd -9 (raw:zstd9).

    xt_bench.py --files 006 007 --tag smoke
    xt_bench.py --tag full                      # all 29 files, default configs

Every config is a real round trip: the decoded file is compared byte for byte
(memcmp) with the original Vectors.vec held in memory. Other members (XML,
comments; < 2 KB per file) are zstd-19 compressed once and added to every row.

Sizes count frames + frame index + layout header. Times:
  compress   = grid scan + layout transform + back-end   (raw layout: back-end only)
  decompress = back-end decode + inverse layout into a preallocated huge-page buffer
MB/s are original bytes (1e6) per second. Threads: all cores for every config.
"""
import argparse
import csv
import glob
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import xtcodec as xc  # noqa: E402

XT = os.path.dirname(HERE)
DATA = os.path.join(os.path.dirname(XT), "data", "extracted")

DEFAULT = ["raw:zstd9",                      # the reference
           "raw:zstd9R", "raw:zstd9L", "raw:bz3",
           "tr8:zstd9", "tr8:zstd9L", "tr8:bz3",
           "pp:zstd9", "pp:zstd9L", "pp:zstd19L", "pp:zstd9R", "pp:zstd3R",
           "pp:bz3", "pp:br9", "pp:lz4hc", "pp:lz4", "pp:dfl9",
           "ppd:zstd9L", "ppd:bz3",
           "rx:zstd9L", "rx:bz3"]


def fmt(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1000 or u == "GB":
            return f"{n:.1f} {u}" if u != "B" else f"{n} B"
        n /= 1000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", nargs="*")
    ap.add_argument("--configs", nargs="*", default=DEFAULT)
    ap.add_argument("--tag", default="run")
    a = ap.parse_args()
    cfgs = [xc.parse(c) for c in a.configs]
    order = sorted(range(len(cfgs)), key=lambda i: xc.LAYOUTS.index(cfgs[i][0]))
    files = sorted(glob.glob(os.path.join(DATA, "*.pat")))
    files = [f for f in files if os.path.isdir(f)]
    if a.files:
        files = [f for f in files if os.path.basename(f)[:3] in a.files]
    ts = time.strftime("%Y%m%d_%H%M%S")
    base = os.path.join(XT, "results", f"xt_bench_{ts}_{a.tag}")
    rows = []
    print(f"{len(files)} files x {len(cfgs)} configs, {xc.NTH} threads -> {base}.csv", flush=True)
    print(f"{'file':5} {'config':12} {'orig':>10} {'comp':>10} {'ratio':>7} {'vsZ9':>7} "
          f"{'cMB/s':>7} {'dMB/s':>7} ok", flush=True)
    for path in files:
        fid = os.path.basename(path)[:3]
        vec = os.path.join(path, "Vectors.vec")
        buf = np.fromfile(vec, dtype=np.uint8)
        other = b"".join(open(os.path.join(path, m), "rb").read()
                         for m in sorted(os.listdir(path)) if m != "Vectors.vec")
        other_c = xc.zstd_compress(np.frombuffer(other, np.uint8), 19).size if other else 0
        n = len(buf)
        orig = n + len(other)
        t0 = time.perf_counter()
        g = xc.Grid(buf)
        t_scan = time.perf_counter() - t0
        if not g.ok:
            g = None
        cache, z9 = {}, None
        results = {}
        for i in order:
            lay, be = cfgs[i]
            name = f"{lay}:{be}"
            if lay != "raw" and g is None:
                lay = "raw"                          # not a clean grid -> plain stream
            if lay not in cache:
                for k in list(cache):                # keep only the current layout in RAM
                    del cache[k]
                t0 = time.perf_counter()
                s = xc.make_layout(lay, buf, g)
                cache[lay] = (s, time.perf_counter() - t0)
            s, t_lay = cache[lay]
            cfn, dfn = xc.BACKENDS[be]
            t0 = time.perf_counter()
            blob = cfn(s)
            t_c = time.perf_counter() - t0 + (t_lay + t_scan if lay != "raw" else 0)
            t0 = time.perf_counter()
            d = dfn(blob, len(s))
            out = xc.undo_layout(lay, d, g, n)
            t_d = time.perf_counter() - t0
            ok = xc.equal(out, buf)
            del d, out
            size = blob.size + other_c + (g.meta_bytes() if lay != "raw" else 0)
            results[name] = dict(file=fid, config=name, original=orig, compressed=size,
                                 comp_s=t_c, decomp_s=t_d, ok=int(ok))
            del blob
        z9 = results.get("raw:zstd9")
        for c in a.configs:
            r = results[c]
            rows.append(r)
            vs = f"{z9['compressed'] / r['compressed']:6.2f}x" if z9 else "   -"
            print(f"{fid:5} {c:12} {fmt(orig):>10} {fmt(r['compressed']):>10} "
                  f"{orig / r['compressed']:6.1f}x {vs:>7} {orig / 1e6 / r['comp_s']:7.0f} "
                  f"{orig / 1e6 / r['decomp_s']:7.0f} {'OK' if r['ok'] else 'FAIL'}", flush=True)
        del buf, cache

    with open(base + ".csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    write_md(base + ".md", rows, a.configs, len(files), a.tag)
    print("DONE", base + ".md", flush=True)


def write_md(path, rows, cfgs, nfiles, tag):
    tot = {}
    for r in rows:
        t = tot.setdefault(r["config"], dict(o=0, c=0, tc=0, td=0, ok=0, n=0))
        t["o"] += r["original"]; t["c"] += r["compressed"]
        t["tc"] += r["comp_s"]; t["td"] += r["decomp_s"]; t["ok"] += r["ok"]; t["n"] += 1
    z9 = tot.get("raw:zstd9")
    lines = [f"# xt bench ({tag}) - {nfiles} files, all {xc.NTH} threads\n",
             "Reference = `raw:zstd9` (plain zstd -9). `vs zstd9` = zstd-9 size / config size; "
             "`size vs zstd9` = size change relative to zstd -9 (negative = smaller).\n",
             "| config | compressed | ratio | vs zstd9 | size vs zstd9 | comp MB/s | decomp MB/s | verified |",
             "|---|---|---|---|---|---|---|---|"]
    for c in sorted(cfgs, key=lambda c: tot[c]["c"]):
        t = tot[c]
        vs = f"{z9['c'] / t['c']:.2f}x" if z9 else "-"
        sv = f"{100 * (t['c'] / z9['c'] - 1):+.1f}%" if z9 else "-"
        lines.append(f"| `{c}` | {fmt(t['c'])} | {t['o'] / t['c']:.1f}x | {vs} | {sv} | "
                     f"{t['o'] / 1e6 / t['tc']:.0f} | {t['o'] / 1e6 / t['td']:.0f} | {t['ok']}/{t['n']} |")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
