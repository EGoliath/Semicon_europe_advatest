#!/usr/bin/env python3
"""Round-2 bench: bk container + zstd sweep, against plain zstd -9 (raw:z9).

    xt2_bench.py --files 007 014 --configs raw:z9 bk4:19l --tag try
    xt2_bench.py --threads 1 ...      # strict single core (run under taskset -c N)
    xt2_bench.py --profile            # per-file structure profile only (no compression)

Every config is a verified round trip (memcmp of the decoded Vectors.vec against
the original in memory). Other members (< 2 KB per file) are zstd-19 compressed
once and added to every row.
compress = grid scan + encode; decompress = decode into a preallocated huge-page buffer.
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
import xt2codec as xc  # noqa: E402

XT = os.path.dirname(HERE)
DATA = os.path.join(os.path.dirname(XT), "data", "extracted")


def fmt(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1000 or u == "GB":
            return f"{n} B" if u == "B" else f"{n:.1f} {u}"
        n /= 1000


def profile(files, base):
    out = []
    print(f"{'file':5} {'pins':>5} {'rows':>10} {'distinct':>10} {'dist%':>7} {'eqprev%':>8}  alphabets")
    for path in files:
        fid = os.path.basename(path)[:3]
        buf = np.fromfile(os.path.join(path, "Vectors.vec"), np.uint8)
        g = xc.Grid(buf)
        if not g.ok:
            print(fid, "not a clean grid"); continue
        h = np.empty(g.rows, np.uint64)
        xc.L.xt2_row_hash(xc.ptr(buf), g.rows, g.W, xc.ptr(h), xc.NTH)
        d = len(np.unique(h))
        e = xc.L.xt2_eq_prev(xc.ptr(buf), g.rows, g.W, xc.NTH)
        al = {0: 0, 1: 0, 2: 0}
        for v in g.nb:
            al[int(v)] += 1
        r = dict(file=fid, pins=g.W, rows=g.rows, distinct_rows=d, distinct_pct=100 * d / g.rows,
                 eq_prev_pct=100 * e / max(1, g.rows - 1), const_pins=al[0], bin_pins=al[1], multi_pins=al[2])
        out.append(r)
        print(f"{fid:5} {g.W:5} {g.rows:10} {d:10} {r['distinct_pct']:6.2f}% {r['eq_prev_pct']:7.2f}%  "
              f"const {al[0]} / 2-sym {al[1]} / 3-4-sym {al[2]}", flush=True)
        del buf, h
    with open(base + ".csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
    print("DONE", base + ".csv")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", nargs="*")
    ap.add_argument("--configs", nargs="*", default=["raw:z9", "bk4:9l", "bk4:19l"])
    ap.add_argument("--threads", type=int, default=os.cpu_count())
    ap.add_argument("--tag", default="run")
    ap.add_argument("--profile", action="store_true")
    a = ap.parse_args()
    xc.set_threads(a.threads)
    files = sorted(f for f in glob.glob(os.path.join(DATA, "*.pat")) if os.path.isdir(f))
    if a.files:
        files = [f for f in files if os.path.basename(f)[:3] in a.files]
    ts = time.strftime("%Y%m%d_%H%M%S")
    if a.profile:
        return profile(files, os.path.join(XT, "results", f"xt2_profile_{ts}_{a.tag}"))
    specs = [(c, xc.parse(c)) for c in a.configs]
    base = os.path.join(XT, "results", f"xt2_bench_{ts}_{a.tag}")
    rows = []
    print(f"{len(files)} files x {len(specs)} configs, {a.threads} threads -> {base}.csv", flush=True)
    print(f"{'file':5} {'config':12} {'orig':>10} {'comp':>10} {'ratio':>7} {'vsZ9':>7} {'cMB/s':>7} "
          f"{'dMB/s':>7} ok  planes(zero/ones/copy/not/stored/xor) mode", flush=True)
    for path in files:
        fid = os.path.basename(path)[:3]
        buf = np.fromfile(os.path.join(path, "Vectors.vec"), np.uint8)
        other = b"".join(open(os.path.join(path, m), "rb").read()
                         for m in sorted(os.listdir(path)) if m != "Vectors.vec")
        oc = len(xc.zstd(np.frombuffer(other, np.uint8), 19)) if other else 0
        n, orig = len(buf), len(buf) + len(other)
        g, t_scan = None, 0.0
        res = {}
        for name, spec in specs:
            t0 = time.perf_counter()
            if spec[0] == "bk" and g is None:
                g = xc.Grid(buf)
                t_scan = time.perf_counter() - t0
                t0 = time.perf_counter()
            pk = xc.compress(spec, buf, g)
            tc = time.perf_counter() - t0 + (t_scan if spec[0] == "bk" else 0)
            t0 = time.perf_counter()
            out = xc.decompress(pk, n)
            td = time.perf_counter() - t0
            ok = xc.equal(out, buf)
            del out
            st = "/".join(str(int(v)) for v in pk.stat) if pk.stat is not None else "-"
            res[name] = r = dict(file=fid, config=name, original=orig, compressed=pk.size + oc,
                                 comp_s=tc, decomp_s=td, ok=int(ok), mode=pk.mode, planes=st,
                                 threads=a.threads)
            z9 = res.get("raw:z9")
            vs = f"{z9['compressed'] / r['compressed']:6.2f}x" if z9 else "     -"
            print(f"{fid:5} {name:12} {fmt(orig):>10} {fmt(r['compressed']):>10} {orig / r['compressed']:6.1f}x "
                  f"{vs:>7} {orig / 1e6 / tc:7.0f} {orig / 1e6 / td:7.0f} {'OK' if ok else 'FAIL'}  {st} {pk.mode}",
                  flush=True)
            rows.append(r)
            del pk
        del buf
    with open(base + ".csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    write_md(base + ".md", rows, [c for c, _ in specs], len(files), a.tag, a.threads)
    print("DONE", base + ".md", flush=True)


def write_md(path, rows, cfgs, nfiles, tag, th):
    tot = {}
    for r in rows:
        t = tot.setdefault(r["config"], dict(o=0, c=0, tc=0, td=0, ok=0, n=0))
        t["o"] += r["original"]; t["c"] += r["compressed"]; t["tc"] += r["comp_s"]
        t["td"] += r["decomp_s"]; t["ok"] += r["ok"]; t["n"] += 1
    z9 = tot.get("raw:z9")
    L = [f"# xt2 bench ({tag}) - {nfiles} files, {th} thread(s)\n",
         "Reference `raw:z9` = plain zstd -9. Size change vs zstd -9: negative = smaller.\n",
         "| config | compressed | ratio | vs zstd9 | size vs zstd9 | comp MB/s | decomp MB/s | verified |",
         "|---|---|---|---|---|---|---|---|"]
    for c in sorted(cfgs, key=lambda c: tot[c]["c"]):
        t = tot[c]
        vs = f"{z9['c'] / t['c']:.2f}x" if z9 else "-"
        sv = f"{100 * (t['c'] / z9['c'] - 1):+.1f}%" if z9 else "-"
        L.append(f"| `{c}` | {t['c'] / 1e6:.1f} MB | {t['o'] / t['c']:.1f}x | {vs} | {sv} | "
                 f"{t['o'] / 1e6 / t['tc']:.0f} | {t['o'] / 1e6 / t['td']:.0f} | {t['ok']}/{t['n']} |")
    open(path, "w").write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
