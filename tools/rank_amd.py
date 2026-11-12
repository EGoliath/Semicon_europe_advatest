#!/usr/bin/env python3
"""Ranking tables for the AMD runs (results/bench_*amd*.csv) -> Markdown.

    tools/rank_amd.py results/bench_*_amd_full_mt.csv [--st results/bench_*_amd_subset_st.csv]

Totals per config (sum of bytes and seconds over files, like testbench).
With --st, a second table compares st / mt / original on the st run's files.
"""
import argparse
import csv
from collections import defaultdict


def load(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def totals(rows, files=None):
    t = defaultdict(lambda: [0, 0, 0, 0.0, 0.0, 0, 0])
    for r in rows:
        if files and r["file"] not in files:
            continue
        x = t[r["config"]]
        x[0] += int(r["orig_bytes"])
        x[1] += int(r["pzst_bytes"])
        x[2] += int(r["pat_zip_bytes"])
        x[3] += float(r["comp_s"])
        x[4] += float(r["decomp_s"])
        x[5] += r["verified"] == "PASS"
        x[6] += 1
    return t


def mb(n):
    if n >= 1e9:
        return f"{n / 1e9:.2f} GB"
    return f"{n / 1e6:.1f} MB" if n >= 1e6 else f"{n / 1e3:.1f} KB"


def table(t, title, ref=None):
    keys = sorted(t, key=lambda k: t[k][1])
    rank_c = {k: i + 1 for i, k in enumerate(sorted(t, key=lambda k: t[k][3]))}
    rank_d = {k: i + 1 for i, k in enumerate(sorted(t, key=lambda k: t[k][4]))}
    out = [f"### {title}", "",
           "| # | config | size | ratio | vs .pat zip | vs " + (ref or "-") +
           " | comp MB/s | decomp MB/s | comp rank | decomp rank | verified |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, k in enumerate(keys, 1):
        o, c, z, tc, td, ok, n = t[k]
        rel = f"{(c / t[ref][1] - 1) * 100:+.1f}%" if ref in t else "-"
        out.append(f"| {i} | `{k}` | {mb(c)} | {o / c:.1f}x | {z / c:.2f}x | {rel} | "
                   f"{o / 1e6 / tc:.0f} | {o / 1e6 / td:.0f} | {rank_c[k]} | {rank_d[k]} | {ok}/{n} |")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mt")
    ap.add_argument("--st")
    ap.add_argument("--ref", default="planesxz:6")
    a = ap.parse_args()
    mt = load(a.mt)
    # compare only on files every config finished (partial runs / skipped files)
    per = defaultdict(set)
    for r in mt:
        per[r["config"]].add(r["file"])
    common = set.intersection(*per.values())
    allf = {r["file"] for r in mt}
    note = "" if common == allf else f", common to all configs; missing: {' '.join(sorted(allf - common))}"
    print(table(totals(mt, common), f"Full corpus ({len(common)} files{note}), multi-core", a.ref))
    if a.st:
        st = load(a.st)
        files = {r["file"] for r in st}
        t = totals(mt, files)
        t.update(totals(st))
        print(table(t, f"Single-core subset ({len(files)} files: {' '.join(sorted(files))})", a.ref))


if __name__ == "__main__":
    main()
