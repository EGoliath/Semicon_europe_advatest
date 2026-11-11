# Pattern File Compression: Algorithm Report

Nov 11, 2026

## Summary

The best method stores each tester pin as its own bit stream, stores duplicate pins once, and compresses the streams in parallel. It makes the 22.8 GB corpus **2.3x to 2.6x smaller than today's `.pat` files**, at up to 1.5 GB/s, and every one of the 232 final test runs restored the files byte for byte.

| Pick | Config | Size | Ratio | vs today's `.pat` zip | Compress | Decompress |
| --- | --- | --- | --- | --- | --- | --- |
| Today's format | `.pat` zip (deflate) | 1.7 GB | 13.4x | 1.0x | – | – |
| Plain zstd (baseline) | `raw:9` | 1.53 GB | 14.9x | 1.1x | 204 MB/s | 617 MB/s |
| Best overall (smallest) | `planesxz:6` | 667.8 MB | 34.9x | 2.6x | 257 MB/s | 808 MB/s |
| Best pure zstd | `planes:19` | 700.6 MB | 33.3x | 2.4x | 309 MB/s | 1030 MB/s |
| Best balanced | `planes:9` | 738.6 MB | 31.6x | 2.3x | 1037 MB/s | 945 MB/s |
| Fastest that beats zip | `planes:3` | 754.3 MB | 30.9x | 2.3x | 1496 MB/s | 996 MB/s |

Config names read `method:level`; `none` means packing only, with no compressor after it. Plain zstd alone barely beats today's files (1.1x). Nearly all the gain comes from reorganising the data before zstd sees it.

## Data and method

Every number comes from the same 29 V93000 SmarTest `.pat` files, run through one test bench that checks each round trip.

- **Corpus:** 29 `.pat` files, 22.8 GB uncompressed, 1.7 GB as today's zip/deflate `.pat` files. Each holds `Program.sprg` (XML), `Vectors.vec` and `Comments.cmt`.
- **Where the data is:** `Vectors.vec` is 99% of the bytes. It is a grid with one line per vector (test cycle) and one character per pin, 5 to 192 pins wide.
- **Symbols:** 2,949 pins use only `0/1`, 122 are constant, and 160 use `H/L/X` (only files 001 and 015, 36 KB in total). No pin uses more than 3 symbols.
- **Machine:** Intel i7-1370P (14 cores / 20 threads), 30 GB RAM, RHEL 9, Python 3.9, zstandard 0.25 (libzstd 1.5.7).
- **Test bench (`testbench.py`):** compresses and decompresses every file per config, then compares a SHA-256 of each restored member with one computed from the source file. Timed decompression includes that SHA-256 check (about 1.8 GB/s alone), for every method.
- **Reading the numbers:** sizes are exact. Speeds vary about ±15% between runs, so speed gaps under 15% are not meaningful. "vs zip" = today's `.pat` size / our size.

## Algorithms tested

Ten experiments, run in order; each row says what was tried, its key number, and what won.

| # | Experiment | Key result | Winner |
| --- | --- | --- | --- |
| 1 | Plain zstd on the raw files (L3, L9, L19) | 14.9x at L3 and L9; 27.0x at L19 but only 7 MB/s (17-file subset) | `raw:9` as the baseline. It barely beats zip (1.1x) |
| 2 | Long-distance matching (128 MiB window) | Raw data L3: 9.2→10.1x and 14.4→16.1x (files 006, 007), but about 10x slower | On, but only for the transformed data, where it is cheap |
| 3 | Transpose: store each pin's time series together (1 byte per symbol) | 1.2–1.9x better than raw (007 L19: 31.5x → 47.6x) | Transpose. Kept as the fallback for pins with 3+ symbols |
| 4 | Bit-packing (`auto`): 1 bit per pin per vector; chunk sweep 16 Ki–1 Mi vectors | Full corpus: 30.7x (L3) to 32.8x (L19); 1 Mi chunks best | **The breakthrough: twice the ratio of plain zstd** |
| 5 | Transform in numpy vs C/OpenMP kernels | Pack 143 MB/s → 11.7 GB/s; unpack 208 MB/s → 22.8 GB/s; end to end ~10x faster | C/OpenMP, identical output |
| 6 | Integrity checksum | SHA-256 1.8 GB/s; CRC32 1.3 GB/s; xxh3-128 21.3 GB/s | xxh3-128: verification costs almost nothing |
| 7 | Thread scaling, 1 to 20 threads (file 003) | Bitpack: 541 MB/s on 1 thread, peak 977 MB/s at 4 threads | 4 threads; one zstd frame decodes on one thread |
| 8 | Ternary packing (5 symbols per byte): `t5`, `t5row`, `t5col`, `mixed` | Pure ternary 18.7–27.8x; `mixed` (0 / 1 / 1.58 bits per pin) 31.0x | `mixed`. Ties bitpack overall; 6–8% smaller on H/L/X files |
| 9 | Best-of hybrid (`best`): encode both ways, keep the smaller | 0.03% (L9) to 0.24% (L19) smaller than `auto`, 2x slower | Not worth it |
| 10 | Ideas from the bit-plane report → `planes` (container v3) | L9: 738.6 MB vs 752.5 MB; L19 compresses 6.4x faster; xz tier 667.8 MB | **`planes`: the new best on size and speed** |

Experiment 10 measured each report idea on the real files before building it. Only four paid: whole-file pin streams (5–6% smaller), storing duplicate pins once (38% of pins are copies), parallel frames, and an xz back end (2–11% smaller than zstd -19).

## Overall ranking

The `planes` family holds the top three sizes and the fastest compression and decompression of anything that beats zip. The table lists all 23 configs run on the full corpus, sorted by size; rank 1 is best, and each config uses its latest run.

| Config | Size | Ratio | vs .pat zip | Compress (MB/s) | Decompress (MB/s) | Size rank | Compress rank | Decompress rank |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `planesxz:9` | 667.0 MB | 34.9x | 2.6x | 179 | 797 | 1 | 20 | 17 |
| `planesxz:6` | 667.8 MB | 34.9x | 2.6x | 257 | 808 | 2 | 18 | 16 |
| `planes:19` | 700.6 MB | 33.3x | 2.4x | 309 | 1030 | 3 | 17 | 5 |
| `best:19` | 709.0 MB | 32.9x | 2.4x | 28 | 892 | 4 | 23 | 12 |
| `mixed:19` | 709.4 MB | 32.9x | 2.4x | 48 | 841 | 5 | 22 | 15 |
| `auto:19` | 710.7 MB | 32.8x | 2.4x | 59 | 862 | 6 | 21 | 13 |
| `planes:9` | 738.6 MB | 31.6x | 2.3x | 1037 | 945 | 7 | 9 | 8 |
| `best:9` | 751.7 MB | 31.0x | 2.3x | 447 | 747 | 8 | 16 | 20 |
| `auto:9` | 751.9 MB | 31.0x | 2.3x | 813 | 788 | 9 | 11 | 19 |
| `mixed:9` | 752.5 MB | 31.0x | 2.3x | 901 | 717 | 10 | 10 | 22 |
| `planes:3` | 754.3 MB | 30.9x | 2.3x | 1496 | 996 | 11 | 6 | 7 |
| `best:3` | 758.3 MB | 30.7x | 2.3x | 650 | 744 | 12 | 13 | 21 |
| `auto:3` | 758.6 MB | 30.7x | 2.3x | 1046 | 794 | 13 | 8 | 18 |
| `mixed:3` | 758.7 MB | 30.7x | 2.3x | 1254 | 897 | 14 | 7 | 11 |
| `t5col:9` | 838.0 MB | 27.8x | 2.0x | 657 | 938 | 15 | 12 | 9 |
| `t5row:9` | 1.18 GB | 19.2x | 1.4x | 467 | 910 | 16 | 15 | 10 |
| `t5:9` | 1.22 GB | 18.7x | 1.4x | 587 | 845 | 17 | 14 | 14 |
| `raw:9` (plain zstd) | 1.53 GB | 14.9x | 1.1x | 204 | 617 | 18 | 19 | 23 |
| `mixed:none` | 2.64 GB | 8.6x | 0.6x | 2000 | 1062 | 19 | 2 | 2 |
| `auto:none` | 2.82 GB | 8.1x | 0.6x | 1906 | 996 | 20 | 4 | 6 |
| `t5col:none` | 4.51 GB | 5.1x | 0.4x | 1733 | 1039 | 21 | 5 | 4 |
| `t5row:none` | 4.68 GB | 4.9x | 0.4x | 1970 | 1095 | 22 | 3 | 1 |
| `t5:none` | 5.14 GB | 4.4x | 0.3x | 2615 | 1039 | 23 | 1 | 3 |

The `:none` configs are fast only because they skip compression; their output is bigger than today's files, so they are not usable.

## Winner per aspect

Among the configs that actually beat today's files, `planes` wins every aspect except the absolute smallest, which goes to its own xz variant.

| Aspect | Winner | Runner-up | Note |
| --- | --- | --- | --- |
| Smallest output | `planesxz:9` (667.0 MB) | `planesxz:6` (667.8 MB) | 0.1% apart; `:6` compresses 44% faster |
| Smallest pure-zstd output | `planes:19` (700.6 MB) | `best:19` (709.0 MB) | And 11x faster to compress than `best:19` |
| Fastest compression that beats zip | `planes:3` (1496 MB/s) | `mixed:3` (1254 MB/s) | 30.9x |
| Fastest decompression that beats zip | `planes:19` (1030 MB/s) | `planes:3` (996 MB/s) |  |
| Fastest compression overall | `t5:none` (2615 MB/s) | `mixed:none` (2000 MB/s) | Packing only: bigger than zip, not usable |
| Fastest decompression overall | `t5row:none` (1095 MB/s) | `mixed:none` (1062 MB/s) | Packing only: bigger than zip |
| Worst | `raw:9` (plain zstd) | – | Barely beats zip and is slow to compress |

## Best overall and best balanced

**Best overall is `planesxz:6`; best balanced is `planes:9`.** Both use the same `planes` layout and differ only in the compressor at the end.

### Best overall: `planesxz:6`

667.8 MB, 34.9x, 2.6x smaller than today's `.pat` files: the smallest output of all. `planesxz:9` is only 0.1% smaller and 30% slower.

- Against the previous best (`mixed:19`), it is 5.9% smaller and compresses 5.4x faster (257 vs 48 MB/s), with similar decompression (808 vs 841 MB/s).
- xz is slow on its own, but here it only sees the packed, de-duplicated bits (1/8 to 1/24 of the original bytes), on all cores in parallel.
- If the rules require pure zstd, the pick is `planes:19`: 700.6 MB, 33.3x, and the fastest decompression of any config that beats zip (1030 MB/s).

### Best balanced: `planes:9`

738.6 MB, 31.6x, 2.3x smaller than zip, at over 1 GB/s compression and about 950 MB/s decompression.

- Against plain zstd (`raw:9`): 2.1x smaller, 5x faster to compress, 1.5x faster to decompress.
- Against the previous balanced pick (`mixed:9`): 1.8% smaller, 15% faster to compress, 32% faster to decompress.
- Level 9 is the last level that stays above 1 GB/s both ways: level 3 is 2% bigger for 44% more speed, level 19 is 5% smaller but 3.4x slower to compress.

### How `planes` works

1. **Pin-major bit streams.** Each pin's waveform becomes one bit stream (1 bit per vector), kept whole for up to 16 Mi vectors (the whole file for 27 of 29 files). Newlines are dropped and regenerated.
2. **Duplicate pins stored once.** Per segment, each pin is stored, or marked all-0, all-1, or "same bits as pin j" after an exact byte comparison. This removes the 38% of pins that are copies in multi-site files; inverted pins match too, because every stream starts at bit 0.
3. **H/L/X pins split in two.** A mask plane marks the X positions and a value plane holds H or L.
4. **Independent frames.** Streams are grouped into ~2 MiB frames, each compressed separately and listed in an index. All cores compress and decompress in parallel.
5. **Integrity.** An xxh3-128 checksum covers the restored bytes and every metadata byte. The tests flip every byte of a compressed file and catch each flip.

Weak spots: the five tiny files (001, 002, 013, 015, 017) come out 100–1,500 bytes bigger than before. Gains are largest on the multi-site files 009, 024, 025 and 026 (5–6% at L9/L19, 17% with xz) and under 1% on the big single-site files 003 and 020.

## What did not pay, and why

Dense, busy pins hold 99.97% of the compressed bytes, so tricks aimed at quiet, clock or constant pins cannot move the ratio on this data. Each idea below was measured on the real files before deciding.

| Idea | Measured on the real files | Why it failed |
| --- | --- | --- |
| Plain zstd at a high level (L19) | 27.0x but 7 MB/s | Too slow; the layout matters more than the level |
| Pure ternary packing (`t5`, `t5row`, `t5col`) | 18.7–27.8x vs 31.0x for bit-packing | 2-symbol pins waste 0.58 bits each in base 3 |
| Best-of hybrid (`best`) | 0.03–0.24% smaller, 2x slower | Both candidates must be encoded |
| XOR / period-aligned prediction | 0.06% smaller | zstd already finds the repeats as matches |
| Run lengths for slow pins, clock descriptors | Slow and clock pins are 0.03% of the output | Nothing left to save there |
| zstd window 2^30–2^31 | Identical output to 2^27 | No repeats further apart than 128 MiB |
| Deduplication across files | 0 shared pins or 64 KiB blocks; one solid stream 0.11% worse | Files share no content (only 002 = 017, 3 KB) |
| Bigger frames (8 MiB) in `planes` | 0.6–1.8% smaller at L19 / xz | Halves compression speed; kept as the `--frame-mib 8` option |

The lesson: measure where the bytes are before building. The ideas that won (bit-packing, whole-file pin streams, duplicate pins, parallel frames) all target the dense pins or the duplication between pins.

## Next steps and where to find it

The code, every benchmark and the full experiment log are on the `Erick_branch` branch of the [GitHub repo](https://github.com/EGoliath/Semicon_europe_advatest/tree/Erick_branch) (`main` is unchanged).

- **Code:** `patzstd/planes.py` (`planes`), `patzstd/codec.py` (earlier methods), `patzstd/kernels.c` (C/OpenMP kernels). The decoder reads every format version.
- **Results:** `results/bench_*.csv` (every run), `results/IDEAS.md` (experiment log), `results/recon.md` (per-pin analysis).
- **Format spec:** `docs/FORMAT.md`. **Tests:** 77 unit tests, all passing.
- **Run it:** `./compress.py data/pat_original/*.pat --mode planes -l 9`, then `./decompress.py out/*.pzst`.

Ideas not tried yet:

1. A context-modelling bit coder as an archive tier. zstd already beats the simple entropy floor by 1.4x, so the remaining structure is higher-order; decoding would run in MB/s, not GB/s.
2. A C decoder that writes straight into tester memory; the pin-major frames already match a per-pin layout.
3. Rebuilding `genVec` / `repeat` loops from repeated vector blocks.
