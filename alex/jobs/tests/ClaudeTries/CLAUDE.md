# CLAUDE.md: tests/ClaudeTries (git branch `claude-tries`)

Local sub-task of the main challenge (see `../../CLAUDE.md`): try the optimizations proposed after the 001–005 split benchmark, namely long-window zstd, entropy analysis, transpose, bit-plane packing, a context model, and an LFSR test. Benchmark everything against plain zstd on the same input.

## Tools (build with WinLibs gcc; `libzstd.dll` is copied here)
- `tries.c`: works with real files.
  - `tries.exe c <zstd|tp|pack>[-long] <level> <in.vec> <out.compr>` compresses to a file.
  - `tries.exe d <in.compr> <out.vec>` decompresses to a file; the method is read from the magic.
  - File formats: zstd output is a plain zstd frame, readable by any zstd tool. pack and tp output is the magic `VPK1` / `VTP1` followed by one zstd frame.
  - Both modes print the wall time and MB/s, where MB/s = 10^6 bytes of `.vec` per second. Verify with `cmp` or `sha256sum`.
  - `--selftest` round-trips CRLF, a missing final newline, 9-symbol columns and multi-block inputs.
  - The earlier in-memory benchmark mode, which produced the screening numbers below, has been removed.
- `bench_files.sh`: compresses everything to disk, then decompresses everything to disk, then compares with `cmp` and `sha256sum`. Edit `S` (the work dir, holding `in/00N/Vectors.vec`) and `T` (the exe) at the top.
  - `zstd`: plain zstd of the file (the baseline).
  - `tp`: per block of R rows, the cells written column by column, then zstd.
  - **`pack`**: per block (default R = 4 MB / pins rows) and per column, the column's own alphabet (k distinct bytes) plus ceil(log2 k) bit planes of the symbol index, then zstd. For `0/1/X` that is an is-`1` plane and an is-`X` plane; constant columns cost 2 bytes per block. Encoding and decoding work in 8-row tiles.
  - `-long`: zstd long-distance matching with a 128 MB window.
- `stats.c`: static conditional entropy under several cell contexts, plus the row-repeat rate.
- `colstats.c`: per-column symbol mix and entropy (order 0, and given the 8 cells above).
- `lfsr.c`: Berlekamp–Massey linear complexity of single columns.

## Findings
- zstd sits near its Huffman floor of 1 bit per literal byte (8x for `0/1` text). The order-0 per-pin entropy alone is 0.43–0.47 bit/cell (17–18x).
- 003–005: about 38–40 scan-channel columns at about 70% `1` (0.85–0.9 bit/cell, 0.76–0.84 given 8 cells above). The rest are nearly constant (about 0.5% deviations). 004/005 are 50% `X`, in whole constant columns.
- **pack** reaches about 32 bits/row on 003, equal to the H|8up estimate (32.25). A context-model coder using own-column history would gain little. It was not built; the estimate is from `colstats`.
- LFSR: the scan channels have the linear complexity of random data (4000 of 8000 bits), so the stimulus is not a plain LFSR stream (likely already compressed on-chip seed data). Only column 11 is partly linear (1121–3623), and it is already cheap. **Negative result.**
- Screening on 200 MB slices of 003 at L9:

  | method | ratio | vs zstd |
  |---|---|---|
  | zstd | 8.38x | baseline |
  | zstd-long | 8.50x | +1% |
  | tp | 13.4x | 1.6x |
  | pack | 19.05x | 2.27x |
  | pack-long | 19.06x | 2.27x |

  - Block size (8k to 2.6M rows) changes pack by under 0.5%.
  - pack at L1 (19.14x) beats zstd at L19 (12.36x, 0.7 MB/s) on the 100 MB slice.

## Full corpus benchmark: whole files 001–005, single thread (2026-11-10)
All runs verified byte-exact: 0 lost bytes everywhere. Log: `scratchpad/data/bench_tries.txt`. The 005 zstd L9 run and the 001 pack runs were repeated: the first 005 decompression was slowed by a system stall, and 001 was rerun after the small-file block fix.

| file | size | zstd L9 | pack L1 | pack L9 | pack L9 vs zstd L9 | compr MB/s (zstd9 / pack1 / pack9) | decomp MB/s (zstd9 / pack1 / pack9) |
|---|---|---|---|---|---|---|---|
| 001 | 20 KB | 769 B | 405 B | 301 B | 2.55x | tiny | tiny |
| 002 | 4.1 MB | 20,930 B | 5,871 B | 4,014 B | 5.21x | 192 / 271 / 200 | 1080 / 527 / 497 |
| 003 | 2.50 GB | 296.07 MB (8.44x) | 129.70 MB (19.27x) | 130.14 MB (19.20x) | 2.28x | 22 / 161 / 158 | 566 / 581 / 652 |
| 004 | 1.44 GB | 160.39 MB (8.99x) | 71.25 MB (20.24x) | 70.34 MB (20.50x) | 2.28x | 29 / 193 / 166 | 709 / 695 / 668 |
| 005 | 1.43 GB | 153.62 MB (9.34x) | 65.61 MB (21.86x) | 64.41 MB (22.27x) | 2.38x | 24 / 197 / 182 | 627 / 732 / 755 |
| **total** | 5.38 GB | 610.1 MB (8.82x) | 266.6 MB (20.18x) | 264.9 MB (20.31x) | **2.30x** | | |

- zstd L1 is 7.00–7.94x on 003–005 at about 157–199 MB/s, so pack L1 is 2.75x smaller than zstd at the same speed.
- Scaling (003 prefixes, pack L1 vs zstd L9):

  | size | pack L1 ratio | pack L1 c/d MB/s | zstd L9 ratio | zstd L9 c/d MB/s |
  |---|---|---|---|---|
  | 25 MB | 19.58x | 147 / 545 | 8.80x | 13 / 396 |
  | 100 MB | 19.14x | 141 / 483 | 8.43x | 18 / 553 |
  | 400 MB | 19.09x | 175 / 613 | 8.37x | 19 / 454 |
  | 1.6 GB | 19.10x | 180 / 616 | 8.36x | 21 / 518 |
  | 2.5 GB | 19.27x | 161 / 581 | 8.44x | 22 / 566 |

  Speeds are flat, so time is linear in size. Codec memory is constant (one block of about 4 MB plus one zstd context).
- 002 (5 pins) decodes at about 500 MB/s against zstd's 1080: the 8-row tile loop costs per cell, and with 5 pins there is little work per row.

## File-based benchmark: `bench_files.sh` (2026-11-10)
The inputs were freshly unpacked from the original archives. Every result was written to disk and re-read from disk. Times are wall clock around each process, including all disk reads and writes.

- **Integrity:**
  - 20 of 20 decompressed files have the same SHA-256 as the original, with 0 bytes differing under `cmp`.
  - For each file, the zstd L9 and pack L9 outputs are identical to each other.
  - No command failed.
- **Stored sizes:** the same as in the in-memory run, plus 4 B for the `VPK1` magic. For example, 003: zstd L9 296,072,517 B vs pack L9 130,142,916 B.
- **Compression, file to file, MB/s:**

  | file | zstd L1 | zstd L9 | pack L1 | pack L9 |
  |---|---|---|---|---|
  | 003 | 104 | 20 | 209 | 142 |
  | 004 | 124 | 24 | 200 | 133 |
  | 005 | 116 | 25 | 212 | 153 |

- **Decompression, file to file:** 84–288 MB/s for both methods, with large swings. This is limited by writing the 1.4–2.5 GB output to disk (about 21 GB written with 8 GB of RAM), not by the decoder. The decoder-only speeds above (600–750 MB/s) assume the output is discarded.

## Full sample corpus 001–029: `bench_all.sh` (2026-11-10)
One archive at a time: unzip, run pack L1, pack L9 and zstd L9 (each to disk), decompress each to disk, check SHA-256 and `cmp`, keep only the end file (pack L9) in `jobs/results/`. Per-file rows are in `jobs/results/bench.csv`; 001 appears twice because `unzip` also picked up the `001.pat` folder, and it is counted once below.
- **Integrity:** 87 of 87 decompressed files are byte-exact. There were 0 zstd fallbacks; every archive is fixed-width.
- **Totals over 24.44 GB of `.vec`:**

  | method | compressed | ratio | compr MB/s | decomp MB/s (disk-bound) |
  |---|---|---|---|---|
  | zstd L9 | 1740.6 MB | 14.04x | 32 | 308 |
  | pack L1 | 814.9 MB | 29.99x | 162 | 259 |
  | pack L9 | 808.7 MB | 30.22x | 103 | 271 |

- **pack L9 vs zstd L9:** 2.15x smaller overall.
  - It is smaller on every file. The range is 1.62x (019) to 5.92x (013).
  - The weakest files are 008, 016, 019 and 022, at about 1.6x each.
  - pack L1 is smaller than pack L9 on 006, 008, 019, 020 and 022.
- The end files take 772 MB. The peak work dir is about 6 GB, under the 60 GB cap.
- The time-complexity proofs (both Θ(MN)) are in `../../../Research/time-complexity.md`.

## Integrity fix after the black-box review (2026-11-10/11)
- **Bug found:** with no checksum, 39 of 50 random bit flips in a pack file decoded with exit code 0 to wrong data.
  - A 0-byte `.compr` decoded with exit code 0 to an empty file.
  - A failed compress left a 0-byte output file behind.
- **Fix in `tries.c`:**
  - The zstd content checksum (`ZSTD_c_checksumFlag`) is on.
  - A frame that ends early is an error ("truncated frame").
  - An empty `.compr` is rejected.
  - `die()` removes the output file being written.
- **After the fix:** 0 silent errors in 427 damaged files. Old files without a checksum still decode, but unprotected. The files in `results/` predate the fix.
- **Black-box rerun on 001–029** with the fixed exe and an independent harness (stdlib zstd, gzip, xz): 161 of 161 byte-exact. pack9 is 2.15x smaller than zstd9 and compresses 3.7x faster. Report: `../../../Research/bench-hackathon-blackbox.md`.
- **Known limits, not fixed:**
  - No fallback for files that are not fixed-width (exit code 1).
  - Memory is about 512 B × column count, so a 10 MB single-line file needs about 5 GB.

## Did not work / not worth it (numbers above)
- zstd long-distance matching: +1% on zstd, +0% on pack.
- Larger pack blocks: ±0.5%.
- Transpose only (tp): 13.4x. It helps, but bit planes are much better.
- LFSR/Berlekamp–Massey: the channels are random-like.
- Context-model coder: estimated ≤ ~1–3% over pack, at a fraction of the speed, so not built.

## Next
- [ ] Multithreaded blocks (each block its own zstd frame) for compression scaling.
- [ ] Reconstruct the `.pat` zip (Program.sprg, Comments.cmt) for an end-to-end byte-exact `.pat`.
- [ ] Faster decode for narrow files (002).
- [ ] Shared coding of the near-constant columns: their rare deviations may sit in the same rows.
