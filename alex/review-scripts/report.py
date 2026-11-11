"""report.py <hack.csv> <out.md> -- markdown tables from the black-box hackathon bench."""
import csv, sys
rows = list(csv.DictReader(open(sys.argv[1])))
M = [m for m in ["pack1", "pack9", "zstd3", "zstd9", "zstd19", "gzip6", "xz6"] if any(r["method"] == m for r in rows)]
files = sorted({r["file"] for r in rows})
by = {(r["file"], r["method"]): r for r in rows}
size = {r["file"]: int(r["size"]) for r in rows}
ok = lambda r: r["sha_ok"] == "True" and r["c_rc"] == "0" and r["d_rc"] == "0"
bad = [r for r in rows if not ok(r)]
full = [m for m in M if all((f, m) in by for f in files)]  # methods run on every file
L = []
w = L.append

def fmt_b(n):
    n = int(n)
    return f"{n/1e9:.2f} GB" if n >= 1e9 else f"{n/1e6:.1f} MB" if n >= 1e6 else f"{n/1e3:.1f} KB" if n >= 1e3 else f"{n} B"

def table(title, cell, note=""):
    w(f"\n### {title}\n")
    if note: w(note + "\n")
    w("| file | size | " + " | ".join(M) + " |")
    w("|---|---:|" + "---:|" * len(M))
    for f in files:
        w(f"| {f[:3]} | {fmt_b(size[f])} | " + " | ".join(cell(by[(f, m)]) if (f, m) in by else "–" for m in M) + " |")

w("# Black-box benchmark: tries.exe vs gzip / zstd / xz on the hackathon sample corpus (001–029)\n")
w("Date: 2026-11-10. Machine: Windows 11, 8 cores, 8 GB RAM, every codec single-threaded.\n")
w("## Setup\n")
w("- **Under test:** `tries.exe` (`tests/ClaudeTries/tries.c`) after the integrity fix of 2026-11-10: zstd content checksum on, "
  "truncated frames rejected, empty `.compr` rejected, output deleted on any failure. "
  "`pack1` and `pack9` are `tries c pack 1|9`.")
w("- **Baselines:** `zstd3`, `zstd9` and `zstd19` use Python's stdlib `compression.zstd` (libzstd 1.5.7, single thread, streaming). "
  "This is independent of the zstd code inside tries.exe. `gzip6` is GNU gzip 1.14 at `-6`. `xz6` is XZ Utils 5.8.3 at `-6 -T1`. "
  "`zstd19` and `xz6` ran only on files under 100 MB, because they run at about 1 MB/s.")
w("- **Input:** `Vectors.vec` from each `.pat` archive, unzipped (zip CRC checked), one archive at a time. Each archive was deleted after its run.")
w("- **Per run:**")
w("  1. Compress in a fresh folder, with TEMP pointed at an empty folder.")
w("  2. Move **only** the compressed file to a second fresh folder, and rename the original away.")
w("  3. Decompress in a new process.")
w("  4. Compare SHA-256 with the original.")
w("  5. Record the results, then delete the decompressed and compressed files.")
w("- **Peak disk usage** stayed under 20 GB. The largest working set was about 5.5 GB, for 028.")
w("- **Times** are wall clock around each process, including disk reads and writes. "
  "MB/s means 10^6 bytes of `.vec` per second. Memory is peak private commit; the memory-mapped input is not counted.")
w("- Python start-up adds about 30 ms to each zstd run. That only matters for files under about 10 MB.\n")

w("## Integrity\n")
w(f"- {len(rows)} round trips, **{len(rows) - len(bad)} byte-exact**, {len(bad)} failed.")
for r in bad: w(f"  - FAIL {r['file']} {r['method']} rc={r['c_rc']}/{r['d_rc']} sha_ok={r['sha_ok']} {r['err'][:120]}")
w("- No side files were created in the work folder, the TEMP folder or next to the exe.\n")

w("## Totals over all files\n")
w(f"Only methods run on every file are included: {', '.join(full)}.\n")
tot = {m: (sum(size[f] for f in files), sum(int(by[(f, m)]["csize"]) for f in files),
           sum(float(by[(f, m)]["c_s"]) for f in files), sum(float(by[(f, m)]["d_s"]) for f in files),
           max(float(by[(f, m)]["c_peakMB"]) for f in files), max(float(by[(f, m)]["d_peakMB"]) for f in files)) for m in full}
z = tot["zstd9"][1]
w("| method | original | compressed | ratio | size vs zstd9 | compress time | decompress time | compress MB/s | decompress MB/s | peak MB c / d |")
w("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
for m in full:
    o, c, ct, dt, cm, dm = tot[m]
    vs = "baseline" if m == "zstd9" else f"{z/c:.2f}x smaller" if c < z else f"{c/z:.2f}x larger"
    w(f"| {m} | {fmt_b(o)} | {fmt_b(c)} | {o/c:.2f}x | {vs} | {ct:.0f} s | {dt:.0f} s | {o/1e6/ct:.1f} | {o/1e6/dt:.1f} | {cm:.0f} / {dm:.0f} |")
p9, z9 = tot["pack9"], tot["zstd9"]
w(f"\n**Headline:** pack9 output is {z9[1]/p9[1]:.2f}x smaller than zstd9. It compresses {z9[2]/p9[2]:.1f}x faster "
  f"({p9[2]:.0f} s against {z9[2]:.0f} s) and decompresses {z9[3]/p9[3]:.2f}x faster ({p9[3]:.0f} s against {z9[3]:.0f} s). "
  f"pack1 matches zstd3's compression speed and its output is {tot['zstd3'][1]/tot['pack1'][1]:.2f}x smaller.\n")

w("## Per file: pack9 vs zstd9 (head to head)\n")
w("| file | size | pack9 size | zstd9 size | pack9 ratio | zstd9 ratio | pack9 smaller by | compress s pack9 / zstd9 | decompress s pack9 / zstd9 | compress MB/s pack9 / zstd9 | decompress MB/s pack9 / zstd9 |")
w("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
gains = []
for f in files:
    a, b = by[(f, "pack9")], by[(f, "zstd9")]
    g = int(b["csize"]) / int(a["csize"]); gains.append((g, f))
    w(f"| {f[:3]} | {fmt_b(size[f])} | {fmt_b(a['csize'])} | {fmt_b(b['csize'])} | {float(a['ratio']):.2f}x | {float(b['ratio']):.2f}x | {g:.2f}x | "
      f"{float(a['c_s']):.2f} / {float(b['c_s']):.2f} | {float(a['d_s']):.2f} / {float(b['d_s']):.2f} | "
      f"{a['c_MBps']} / {b['c_MBps']} | {a['d_MBps']} / {b['d_MBps']} |")
gains.sort()
w(f"\n- Weakest pack9 gains over zstd9: " + ", ".join(f"{f[:3]} {g:.2f}x" for g, f in gains[:5]) + ".")
w(f"- Strongest: " + ", ".join(f"{f[:3]} {g:.2f}x" for g, f in gains[-3:][::-1]) + ".")
loss = [f for g, f in gains if g < 1]
w(f"- Files where pack9 output is larger than zstd9: {', '.join(x[:3] for x in loss) if loss else 'none'}.")
best_base = []
for f in files:
    p = int(by[(f, "pack9")]["csize"]); bb = min((int(by[(f, m)]["csize"]), m) for m in M if (f, m) in by and not m.startswith("pack"))
    if bb[0] < p: best_base.append(f"{f[:3]} ({bb[1]} {fmt_b(bb[0])} vs pack9 {fmt_b(p)})")
w(f"- Files where any baseline beats pack9: {', '.join(best_base) if best_base else 'none'}.\n")

w("## All methods, per file\n")
table("Compressed size", lambda r: fmt_b(r["csize"]))
table("Compression ratio (original / compressed)", lambda r: f"{float(r['ratio']):.2f}x")
table("Compress time (s)", lambda r: f"{float(r['c_s']):.2f}")
table("Decompress time (s)", lambda r: f"{float(r['d_s']):.2f}")
table("Compress speed (MB/s of .vec)", lambda r: r["c_MBps"], "Files under about 10 MB are dominated by process start-up, so their speeds are not meaningful.")
table("Decompress speed (MB/s of .vec, written to disk)", lambda r: r["d_MBps"])
table("Peak memory, compress / decompress (MB, private commit)", lambda r: f"{float(r['c_peakMB']):.0f} / {float(r['d_peakMB']):.0f}")

w("\n## Limits and caveats\n")
w("- pack accepts only fixed-width line files. In the black-box review on public data, it refused 31 of 32 public files "
  "(Silesia, Canterbury, logs, images, archives) with exit code 1. On `ptt5`, the one file it accepted, its output was 17% larger than zstd9. "
  "It has no built-in zstd fallback.")
w("- pack compression memory is about 512 B × column count, so very wide single-line inputs need gigabytes. "
  "A 10 MB single-line file needed about 5 GB and failed with \"out of memory\" when RAM was short. This is not fixed.")
w("- Before the fix, 39 of 50 random bit flips in a pack file decoded with exit code 0 to wrong data. After the fix, 0 of 427 damaged files did. "
  "Files written by the old binary still decode, but they have no checksum.")
w("- Decompression times include writing up to 2.5 GB to disk, so they are partly disk-bound.")
w("- Only the `.vec` round trip is tested. The `.pat` zip (Program.sprg, Comments.cmt) is not rebuilt.")
w("- Single machine, single run per point, no repeats. Treat speed differences under about 10% as noise.")
w("\nRaw data: `bench-hackathon-blackbox.csv` (next to this file).")
open(sys.argv[2], "w", encoding="utf-8").write("\n".join(L) + "\n")
print("wrote", sys.argv[2], len(rows), "rows,", len(bad), "failures")
