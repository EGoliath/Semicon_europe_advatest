# alex/ – `pack` codec (C, per-column bit planes + zstd)

A separate prototype line, developed locally and moved into this repo unchanged. It does not share code with `patzstd/`.

## Layout

```
alex/
  jobs/                   copy of the local working repo (data and results excluded, see .gitignore)
    tests/ClaudeTries/    tries.c: the pack codec (main result), plus stats.c, colstats.c, lfsr.c, bench_*.sh
    tests/Compression/    vcompress.c: plain zstd baseline
    tests/Split/          split.c: drive/read split + zstd (1.3x over zstd on 001)
    tests/Visualization/  vecview.c: .vec viewer
    tests/scientific-optimization/  logic-minimisation survey (research.md)
    Chellenge/            challenge brief (PDF)
  Research/               black-box benchmark report + CSV, time-complexity proofs
  review-scripts/         independent black-box harness (Python + bash): bench, corruption test, tables
```

The `CLAUDE.md` files are the per-folder notes, kept as written. Their relative data paths (`../hackathon/hackathon/`, `results/`, scratchpad logs) point at the original local layout, which is not in this repo.

## How `pack` works

For each block of rows (default 4 MB / pin count) and each column:
1. Store the column's own alphabet (k distinct bytes).
2. Store ceil(log2 k) bit planes of the symbol index. For `0/1/X` that is an is-`1` plane plus an is-`X` plane. A constant column costs 2 bytes per block.
3. Compress everything with one zstd frame, with the content checksum on.

The format is the magic `VPK1` followed by that zstd frame. It works only on fixed-width-line `.vec` files and runs single-threaded. Time is Θ(rows × columns) for both directions (`Research/time-complexity.md`).

```
gcc -O2 -Wall tries.c -o tries.exe libzstd.dll        # libzstd 1.5.7
tries.exe c pack 9 Vectors.vec out.compr
tries.exe d out.compr Vectors.vec
tries.exe --selftest
```

## Current results (sample corpus 001–029, 24.44 × 10⁹ B of `Vectors.vec`)

Independent black-box rerun after the integrity fix. 161 of 161 round trips are byte-exact (SHA-256). Every codec ran single-threaded on Windows 11 (8 cores, 8 GB RAM), and times include disk I/O. Full report: [`Research/bench-hackathon-blackbox.md`](Research/bench-hackathon-blackbox.md).

| method | compressed | ratio | vs zstd9 | compress time | decompress time | decompress MB/s |
|---|---:|---:|---:|---:|---:|---:|
| zstd9 (baseline) | 1,740,586,211 B | 14.04x | 1.00x | 751 s | 101.0 s | 242 |
| pack1 | 814,933,574 B | 29.99x | 2.14x smaller | 135 s | 82.8 s | 295 |
| **pack9** | **808,661,747 B** | **30.22x** | **2.15x smaller** | **204 s** | **78.5 s** | **311** |

- pack9 is smaller than zstd9 on every file, by 1.62x (019) up to 5.91x (013).
- Compared with zstd19 on the 8 files under 100 MB (zstd19 runs at about 1 MB/s), pack9 is 73.4x against 42.2x, which is 1.74x smaller.
- Integrity: the zstd checksum is on, and truncated or empty input is rejected. A failed run deletes its output. There were 0 silent errors across 427 deliberately damaged files.

### Against `planes` in this repo (same 29 files)

The root README reports `planes:9` at 738.6 MiB (≈ 774.5 × 10⁶ B, 31.6x). pack9 is 808.7 × 10⁶ B (30.2x), so it is about 4% larger. The `planes` measurements use multiple threads on another machine, so the speeds are not comparable.

## Known limits (not fixed)

- There is no fallback for files that are not fixed-width: `pack` exits with code 1 (31 of 32 public-corpus test files).
- Memory is about 512 B × column count, so a 10 MB single-line file needs about 5 GB.
- It is weak on non-pattern data: 17% worse than zstd9 on ptt5, and about 2x larger on tiny files.
- It does not rebuild the `.pat` zip (`Program.sprg`, `Comments.cmt`), so only `Vectors.vec` is round-tripped.
- Speeds are from single runs.
