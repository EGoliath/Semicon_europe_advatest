# Ideas tried – benchmark log

Machine: Intel i7-1370P (14 cores / 20 threads), 30 GB RAM, RHEL 9, Python 3.9,
zstandard 0.25 (libzstd 1.5.7). Corpus: 29 `.pat` files, 22.8 GB of uncompressed
members, **1.7 GB as compressed today** (`.pat` = zip/deflate).
Every result below is a verified bit-exact round-trip unless noted.

"vs zip" = size of today's `.pat` files / size of our output (higher is better).

---

## 0. Reference: today's format
`.pat` zip (deflate): 22.8 GB -> 1.7 GB, **13.4x**.

## 1. Plain zstd on the raw members (baseline)
| config | ratio | vs zip | comp MB/s | decomp MB/s | source |
|---|---|---|---|---|---|
| zstd L3 (17 small files) | 14.9x | 0.9x | 308 | 542 | bench_20261111_011004 |
| zstd L9 (all 29) | 14.9x | 1.1x | 199–210 | 520–772 | bench_20261111_013328 / _full_c |
| zstd L19 (17 small files) | 27.0x | 1.6x | 7 | 610 | bench_20261111_011004 |

Conclusion: plain zstd at any practical level is barely better than today's zip.

## 2. Long-distance matching (LDM, 128 MiB window) on raw data
File 006 / 007 at L3: ratio 9.2→10.1x and 14.4→16.1x, but compression speed
drops ~10x (3400→320 MB/s). Small gain, kept on for the transformed stream only
(where the stream is 8x smaller, so the cost is negligible).

## 3. Transpose (pin-major, 1 byte/symbol) + zstd
Store each pin's time series contiguously instead of vector by vector.
| file | raw L3 | transpose L3 | raw L19 | transpose L19 |
|---|---|---|---|---|
| 006 | 10.1x | 14.6x | 20.0x | 23.1x |
| 007 | 16.1x | 27.3x | 31.5x | 47.6x |

Gain 1.2–1.9x. Used as fallback when a pin has 3+ symbols (files 001, 015).

## 4. Bit-packing (1 bit per pin per vector) + zstd  ← main idea
Every pin of 27/29 files toggles between only 2 symbols (`0/1`, `L/H`, `X/L`…),
so a vector needs 1 bit per pin instead of 8 bits + newline.
Chunk size sweep (file 007, L3 → L19):

| chunk rows | 006 L3 | 006 L19 | 007 L3 | 007 L19 |
|---|---|---|---|---|
| 16 Ki | 25.2x | 26.5x | 50.1x | 54.9x |
| 64 Ki | 25.0x | 26.5x | 53.2x | 56.9x |
| **1 Mi (chosen)** | 25.2x | 26.6x | 57.1x | 62.8x |

Full corpus (bench_20261111_020105_full_c):
| config | size | ratio | vs zip | comp MB/s | decomp MB/s |
|---|---|---|---|---|---|
| bitpack + zstd L3 | 758.6 MB | 30.7x | 2.3x | 1028 | 794 |
| bitpack + zstd L9 | 751.9 MB | 31.0x | 2.3x | 730 | 778 |
| bitpack + zstd L19 | 710.7 MB | **32.8x** | **2.4x** | 57 | 900 |

Level matters little after bit-packing (30.7x → 32.8x): the transform does the work.

## 5. Transform implementation: numpy → C/OpenMP kernels
Profile of file 007 (703 MB) with numpy: bit-pack 143 MB/s, un-pack 208 MB/s,
zstd on the packed stream 3400 MB/s → the transform was ~90% of the time.

| kernel | numpy | C / OpenMP |
|---|---|---|
| analyse (symbol scan) | 413 MB/s | 7.3 GB/s |
| pack | 143 MB/s | 11.7 GB/s |
| unpack | 208 MB/s | 22.8 GB/s |
| transpose | 643 MB/s | 7.2 GB/s |
| untranspose | – | 13.6 GB/s |

End-to-end, bitpack L9, 17 small files: comp 82 → 963 MB/s, decomp 146 → 1023 MB/s.

## 6. Integrity checksum
| hash | MB/s |
|---|---|
| sha256 | 1843 |
| crc32 (zlib) | 1336 |
| **xxh3-128 (chosen)** | 21283 |

The container stores xxh3-128 per member; the test bench separately verifies
SHA-256 computed from the source files (outside the timed section).

## 7. Thread scaling (file 003, 2.3 GB, L9)
| threads | raw zstd comp | bitpack comp | raw decomp | bitpack decomp |
|---|---|---|---|---|
| 1 | 46 | 541 | 636 | 742 |
| 2 | 87 | 663 | 550 | 766 |
| 4 | 130 | **977** | 634 | **933** |
| 8 | 170 | 934 | 639 | 796 |
| 12 | 176 | 974 | 625 | 825 |
| 16 | 177 | 922 | 637 | 831 |
| 20 | 176 | 875 | 636 | 775 |

- Single-threaded, bitpack is already 12x faster than plain zstd (541 vs 46 MB/s),
  because zstd only has to compress 1/8 of the data.
- Scaling saturates at ~4 threads: the remaining serial parts are the Python
  driver, one zstd decoder thread (a single zstd frame cannot be decoded in
  parallel) and memory bandwidth.
- Next step to make decompression scale: write each chunk as an independent zstd
  frame so chunks can be decoded in parallel.

## Not tried yet / backlog
- Independent per-chunk frames → parallel decode (speed scaling).
- Duplicate pin columns (multi-site patterns repeat the same pins, e.g. 001 has 3
  identical 64-pin groups) → store each unique column once.
- Run-length / period detection per pin (clocks) before zstd.
- zstd dictionary trained across the corpus; window size > 128 MiB.
- Restoring `genVec`/`repeat` loops from repeated vector blocks.

---

## 8. Ternary packing (3^5 = 243 ≤ 256: 5 symbols per byte)

Full details: `results/ternary_breakdown.md`, `results/ternary_explore.md`,
format in `docs/FORMAT.md`. Full corpus run: bench_20261111_024447_ternary_full
(319 runs, all bit-exact); t5 re-run after optimisation: bench_20261111_025819_t5_opt_hist.

Data facts that decide the outcome (results/data_inspection.txt):
per pin, 2,949 pins use `0/1`, 119 are always `X`, 3 always `0`, 160 use `H/L/X`
(only in 001 and 015, 36 KB together). No pin uses more than 3 symbols.
Seven files use exactly `0/1/X` overall, but there every `X` sits on a pin that
is always `X`.

| config (whole corpus) | size | ratio | vs .pat zip | vs plain zstd L9 | comp MB/s | decomp MB/s |
|---|---|---|---|---|---|---|
| plain zstd L9 (baseline) | 1.5 GB | 14.9x | 1.1x | – | 248 | 848 |
| t5 generic stream, packing only | 5.1 GB | 4.4x | 0.3x | 3.4x larger | 2615 | 1039 |
| t5 generic stream + zstd L9 | 1.2 GB | 18.7x | 1.4x | 20% smaller | 587 | 845 |
| t5row + zstd L9 | 1.2 GB | 19.2x | 1.4x | 23% smaller | 467 | 910 |
| t5col + zstd L9 | 838 MB | 27.8x | 2.0x | 46% smaller | 657 | 938 |
| mixed + zstd L9 | 752.5 MB | 31.0x | 2.3x | 52% smaller | 931 | 988 |
| bitpack + zstd L9 (existing) | 751.9 MB | 31.0x | 2.3x | 52% smaller | 867 | 963 |

* Ternary packing beats plain zstd, but pure ternary (t5, t5row, t5col) is
  larger than binary bit-packing on 27/29 files: 2-symbol pins waste
  log2(3) = 1.58 bits vs 1 bit.
* `mixed` (binary for 2-symbol pins, ternary only for 3-symbol pins) ties
  bitpack overall (+0.08%), wins by 6–7% on the two H/L/X files (001, 015).
* Escape overhead (packing only, 16 MiB samples): in-band tokens 4.28x vs
  naive escape 4.05x vs span blocks 4.05x on W=76 files; span blocks only win
  when the alphabet does not cover the line (001: 1.65x vs 1.53x).
* Optimisations: Python reference 4.6/11 MB/s → C 1.7/3.0 GB/s (LUT decode
  1.8x faster than div/mod) → parallel blocks 13.5/20.8 GB/s. The real
  bottleneck was alphabet selection (numpy bincount, 850 MB/s); a C histogram
  gave 6.8 GB/s and raised t5 end-to-end compression from 581 to 2615 MB/s
  (packing only) and 353 to 587 MB/s (+ zstd L9), output unchanged.
* Block size: ≥ 256 KiB loses nothing in ratio; 4 KiB blocks cost 1% ratio
  and 15x speed (per-block overhead).

Verdict: lossless and well tested, but not worth pursuing as the main method
for this corpus; keep `mixed` as an option for H/L/X compare pins.

---

## 9. Best-of hybrid (`best`): earlier auto (bitpack/transpose) vs mixed, keep smaller

Each candidate is compressed into its own zstd frame; the smaller frame is
appended to the output (zstd frames concatenate; decoder reads across frames).
Run: bench_20261111_031452_best_hybrid (290 runs, all bit-exact).

| config | size | ratio | vs .pat zip | comp MB/s | decomp MB/s |
|---|---|---|---|---|---|
| plain zstd L9 | 1.5 GB | 14.9x | 1.1x | 227 | 746 |
| auto L3 / L9 / L19 | 758.6 / 751.9 / 710.7 MB | 30.7 / 31.0 / 32.8x | 2.3 / 2.3 / 2.4x | 1046 / 813 / 59 | 794 / 788 / 862 |
| mixed L3 / L9 / L19 | 758.7 / 752.5 / 709.4 MB | 30.7 / 31.0 / 32.9x | 2.3 / 2.3 / 2.4x | 1254 / 879 / 53 | 897 / 873 / 966 |
| best L3 / L9 / L19 | 758.3 / 751.7 / 709.0 MB | 30.7 / 31.0 / 32.9x | 2.3 / 2.3 / 2.4x | 650 / 447 / 28 | 744 / 747 / 892 |

* Winners at L9: bitpack 23 files, mixed 6 (001, 004, 006, 013, 015, 016);
  at L19 mixed wins 19 files.
* Gain over auto: 0.03% (L9) and 0.24% (L19) on the corpus; 8.4–8.6% on the
  two H/L/X files at L9. Even when bitpack wins, best is 0.01–1% smaller than
  auto because the vector member gets its own fresh zstd frame.
* Cost: compression ~2x slower (both candidates are encoded). Decompression
  is the same code path (differences are run-to-run noise, ±15%).
* Not strictly "never larger": a new frame costs a few bytes; on 015 at L19
  best is 7 bytes (0.55%) larger than auto.

Verdict: the size gain is too small to justify halving compression speed.
Plain `mixed` gets almost all of it (L19: 709.4 vs 709.0 MB) at full speed.
