# Semicon Europe × Advantest challenge – lossless compression of V93000 pattern files

Lossless compression of SmarTest `.pat` pattern files with **zstd**, after a
pattern-aware transform: **each pin's waveform is stored with only the bits it needs**.
Every result below was checked for an exact bit-for-bit round trip (xxh3-128 inside
the container, plus an independent SHA-256 check in the test bench).

> Full write-up of every algorithm, ranking and verdict: [`REPORT.md`](REPORT.md).

## TL;DR

| | config | size (22.8 GB corpus) | ratio | vs today's `.pat` zip | compress | decompress |
|---|---|---|---|---|---|---|
| Today's format | `.pat` zip (deflate) | 1.7 GB | 13.4x | 1.0x | – | – |
| Plain zstd (baseline) | `raw:9` | 1.53 GB | 14.9x | 1.1x | 204 MB/s | 617 MB/s |
| Previous best (v2) | `mixed:19` | 709.4 MB | 32.9x | 2.4x | 48 MB/s | 841 MB/s |
| 🏆 **Best overall (smallest practical)** | **`planesxz:6`** | **667.8 MB** | **34.9x** | **2.6x** | 257 MB/s | 808 MB/s |
| 🥇 **Best pure zstd** | **`planes:19`** | **700.6 MB** | **33.3x** | **2.4x** | 309 MB/s | **1030 MB/s** |
| ⚖️ **Best balanced** | **`planes:9`** | **738.6 MB** | **31.6x** | **2.3x** | **1037 MB/s** | **945 MB/s** |
| ⚡ Fastest config that still beats zip | `planes:3` | 754.3 MB | 30.9x | 2.3x | 1496 MB/s | 996 MB/s |

Config names are `mode:level` (`none` = packing only, no back-end compressor).
`planes*` is the v3 container (section 10); `planesxz` uses xz/LZMA frames instead of zstd (archive tier).
Measured on an Intel i7-1370P (14 cores / 20 threads, 30 GB RAM, RHEL 9,
Python 3.9, zstandard 0.25 / libzstd 1.5.7), on all 29 `.pat` files (22.8 GB uncompressed).
Speeds vary by ±15% from run to run; decompression speeds include the test bench's SHA-256 check. Sizes are exact.

---

## Top 20 of all tests vs plain zstd -9 (2026-11-12)

All 29 files (24.44 GB = 22.8 GiB uncompressed), all 20 threads, every row a verified bit-exact round trip.
Sizes here are in **MB = 10⁶ bytes** (the tables further down use MiB, so their numbers look ~5% smaller).
Reference: **plain `zstd -9` = 1740.7 MB**. "Saved" = 1740.7 MB − size.

The `amd_*_mt` builds of `planesxz`, `planes`, `best`, `mixed` and `auto` give exactly the same size
as the originals and are left out. With them: `extra_tests/results/TOP25_ALL_TESTS_20261112.md`.

| # | algorithm | from | size | saved vs zstd-9 | % smaller | × smaller | comp MB/s | decomp MB/s |
|---|---|---|---|---|---|---|---|---|
| 1 | `amd_pcm_mt:3` | `patamd/` | 657.8 MB | 1082.9 MB | **62.2%** | **2.65×** | 49 | 51 |
| 2 | `amd_pcm_mt:2` | `patamd/` | 659.0 MB | 1081.7 MB | 62.1% | 2.64× | 62 | 55 |
| 3 | `amd_planesbwt_mt:1` | `patamd/` | 687.3 MB | 1053.4 MB | 60.5% | 2.53× | 477 | 438 |
| 4 | `planesxz:9` | `patzstd/` | 699.4 MB | 1041.3 MB | 59.8% | 2.49× | 194 | 813 |
| 5 | `planesxz:6` | `patzstd/` | 700.2 MB | 1040.5 MB | 59.8% | 2.49× | 270 | 781 |
| 6 | `pp:zstd19L` | `extra_tests/` round 1 | 732.5 MB | 1008.2 MB | 57.9% | 2.38× | 73 | **3197** |
| 7 | `bkA:19lg` | `extra_tests/` round 2 | 732.9 MB | 1007.8 MB | 57.9% | 2.38× | 247 | 2213 |
| 8 | `bk16:19lg` | `extra_tests/` round 2 | 733.6 MB | 1007.1 MB | 57.9% | 2.37× | 231 | 2059 |
| 9 | `planes:19` | `patzstd/` | 734.6 MB | 1006.1 MB | 57.8% | 2.37× | 300 | 967 |
| 10 | `best:19` | `patzstd/` | 743.4 MB | 997.3 MB | 57.3% | 2.34× | 24 | 722 |
| 11 | `mixed:19` | `patzstd/` | 743.8 MB | 996.9 MB | 57.3% | 2.34× | 46 | 750 |
| 12 | `auto:19` | `patzstd/` | 745.2 MB | 995.5 MB | 57.2% | 2.34× | 49 | 641 |
| 13 | `planes:9` | `patzstd/` | 774.5 MB | 966.2 MB | 55.5% | 2.25× | 1160 | 936 |
| 14 | `pp:zstd9L` | `extra_tests/` round 1 | 777.3 MB | 963.4 MB | 55.3% | 2.24× | 1143 | 1833 |
| 15 | `bk4:9g` | `extra_tests/` round 2 | 780.2 MB | 960.5 MB | 55.2% | 2.23× | 994 | 1633 |
| 16 | `best:9` | `patzstd/` | 788.2 MB | 952.5 MB | 54.7% | 2.21× | 530 | 651 |
| 17 | `auto:9` | `patzstd/` | 788.5 MB | 952.2 MB | 54.7% | 2.21× | 813 | 788 |
| 18 | `mixed:9` | `patzstd/` | 789.1 MB | 951.6 MB | 54.7% | 2.21× | 901 | 717 |
| 19 | `planes:3` | `patzstd/` | 790.9 MB | 949.8 MB | 54.6% | 2.20× | **1512** | 1139 |
| 20 | `bk4:3g` | `extra_tests/` round 2 | 794.1 MB | 946.6 MB | 54.4% | 2.19× | 1485 | 1648 |
| ref | plain `zstd -9` | – | 1740.7 MB | 0 | 0% | 1.00× | ~510 | ~1230 |

Speeds come from three different bench scripts that time things slightly differently
(plain zstd -9 measured 505–517 MB/s compress and 1211–1245 MB/s decompress across them),
so compare speeds only roughly; sizes are exact.

---

## Presentation shortlist: #4, #6, #7, #8, #9, #10

Six algorithms from the top 10 that show the different ways we got to **about 2.4–2.5× smaller than zstd -9**.

| # | algorithm | in one sentence | size | % smaller than zstd-9 | × smaller | compress | decompress |
|---|---|---|---|---|---|---|---|
| 4 | `planesxz:9` | bit planes + duplicate removal, packed with **xz** (strongest classic compressor) | 699.4 MB | **59.8%** | **2.49×** | 194 MB/s | 813 MB/s |
| 6 | `pp:zstd19L` | bit planes, **one big zstd-19 stream** per file that can reuse patterns from far back | 732.5 MB | 57.9% | 2.38× | 73 MB/s | **3197 MB/s** |
| 7 | `bkA:19lg` | bit planes + skip constant/duplicate/inverted pins, whole file in one block, many small zstd-19 pieces | 732.9 MB | 57.9% | 2.38× | 247 MB/s | 2213 MB/s |
| 8 | `bk16:19lg` | same as #7, but cut into **independent blocks of 16 M rows** (any block can be read alone) | 733.6 MB | 57.9% | 2.37× | 231 MB/s | 2059 MB/s |
| 9 | `planes:19` | our main codec: bit planes + duplicate removal + zstd-19 in parallel frames, with an integrity checksum | 734.6 MB | 57.8% | 2.37× | 300 MB/s | 967 MB/s |
| 10 | `best:19` | compress each file **two ways** (`auto` and `mixed`) and keep the smaller one | 743.4 MB | 57.3% | 2.34× | 24 MB/s | 722 MB/s |
| ref | plain `zstd -9` | the file as it is, standard zstd | 1740.7 MB | 0% | 1.00× | ~510 MB/s | ~1230 MB/s |

### The common idea (why all six beat zstd by more than 2×)

A pattern file is a big table: **one line per test cycle, one character per pin**
(`0`, `1`, `H`, `L`, `X` …). In the file each character costs 8 bits, but a pin only ever
uses 1 to 3 different values, so it really needs **0, 1 or 2 bits**.

All six algorithms do the same three things before compressing:

1. **Shrink every character to the bits it really needs.** A pin that is always `X` costs nothing;
   a `0/1` pin costs 1 bit per cycle. That alone makes the data ~8× smaller.
2. **Turn the table sideways.** Instead of storing the file line by line (all pins of cycle 1,
   then all pins of cycle 2 …), each pin's whole history is stored in one piece
   (a "bit plane"). A clock then looks like `0101010101…` and a slow control line like
   `0000…1111…`: long, regular runs that a compressor squeezes very well.
3. **Then compress** with a standard compressor (zstd or xz).

Plain zstd sees the original text line by line and never gets the chance to find these
patterns. That is the whole gap between 1740 MB and ~730 MB.

### What makes each one different

- **#4 `planesxz:9`, smallest of the six.** Same bit planes as #9, but compressed with
  **xz** instead of zstd. xz searches harder, so it is ~5% smaller than #9, but compression is
  slower (194 vs 300 MB/s) and so is decompression (813 vs 967 MB/s). Good for long-term archive storage.
- **#6 `pp:zstd19L`, fastest to decompress (3.2 GB/s).** The simplest version: bit planes,
  then **one single zstd-19 stream per file** with a very long memory (`L` = "long mode",
  it can reuse a pattern seen up to 2 GB earlier). Decompression is very fast, but compression is slow
  (73 MB/s) and you always have to decompress the whole file.
- **#7 `bkA:19lg`, best speed/size mix of the zstd family.** Adds **smart skipping**:
  pins that are all 0, all 1, an exact copy of another pin, or its exact inverse are not
  stored at all, just a 2-byte note ("same as pin 12"). 38% of pins are copies (the same
  signal sent to several test sites). The rest is split into many small zstd-19 pieces that all
  CPU cores compress and decompress at the same time (`g`), which is why it is 3× faster to compress than #6.
- **#8 `bk16:19lg`, the same plus random access.** Like #7, but the file is first cut into
  **independent blocks of 16.8 million cycles**. Any block can be decompressed without the
  others (e.g. to load just part of a pattern into the tester). That costs only **0.1%**
  in size compared with #7.
- **#9 `planes:19`, our production codec.** The same ideas as #7 (bit planes, duplicate pins,
  parallel frames) inside our full container format, which also stores a **checksum
  (xxh3-128)** so a corrupted file is always detected. Its decompression number is lower than #7/#8
  partly because its test bench also runs a SHA-256 check on the output (round 2 measured in memory).
- **#10 `best:19`, try both and keep the winner.** Compresses every file with two older
  methods (`auto` and `mixed`) and keeps the smaller one. It works, but it does all the work twice
  (24 MB/s) for only 0.05% gain, and newer methods (#4–#9) are smaller *and* faster.

**Takeaway for the slide:** the big win (2.3×) comes from **reorganising the data per pin
at the bit level**. The choice of compressor (zstd, xz) and the container details only move
the result by a few percent; they mainly decide speed, random access and robustness.

---

## The idea in one picture

`Vectors.vec` (99% of the data) is a grid: one line per vector (test cycle), one
character per pin. Today every character costs 8 bits plus a newline per line.

```
row-major (today)          pin-major + bit-packed (mixed)
0110X1...                  pin 0: 000000…   ← constant pin, 0 bits
0110X1...       ──────►    pin 1: 111111…   ← 1 bit/vector
0111X1...                  pin 3: 001011…   ← 1 bit/vector
                           pin 4: X  (always X: 0 bits, header only)
```

Per-pin alphabets measured on the whole corpus (`results/data_inspection.txt`):

| what a pin uses | number of pins |
|---|---|
| a single symbol (constant, e.g. always `X`) | 122 |
| 2 symbols (`0/1`) | 2,949 |
| 3 symbols (`H/L/X`, files 001 and 015 only) | 160 |
| more than 3 symbols | 0 |

So a vector carries about 1 bit per pin, not 8. Storing each pin's time series
on its own turns clocks, constant pins and slow control lines into long runs that
zstd compresses extremely well.

---

## Results by section – what won in each experiment

Full log with every number: [`results/IDEAS.md`](results/IDEAS.md). Raw data: `results/bench_*.csv / .md`.

### 1. Plain zstd on the raw members (baseline)
| config | ratio | vs zip | comp MB/s | decomp MB/s |
|---|---|---|---|---|
| zstd L3 (17 small files) | 14.9x | 0.9x | 308 | 542 |
| **zstd L9 (all 29)** | 14.9x | 1.1x | 199–248 | 520–848 |
| zstd L19 (17 small files) | 27.0x | 1.6x | 7 | 610 |

**Best: `raw:9`.** It is the reference point, but it is barely better than today's zip,
and L19 is far too slow (7 MB/s). A generic compressor alone isn't enough.

### 2. Long-distance matching (LDM, 128 MiB window)
Raw data, L3: 9.2→10.1x and 14.4→16.1x (files 006 / 007), but compression is about 10x slower.
**Best: LDM on, but only for the transformed stream**, which is 8x smaller, so the cost is negligible there.

### 3. Transpose (pin-major, 1 byte per symbol) + zstd
| file | raw L3 | transpose L3 | raw L19 | transpose L19 |
|---|---|---|---|---|
| 006 | 10.1x | 14.6x | 20.0x | 23.1x |
| 007 | 16.1x | 27.3x | 31.5x | 47.6x |

**Best: transpose**, 1.2–1.9x better than raw. Kept as the fallback for pins with 3+ symbols in `auto`.

### 4. Bit-packing (1 bit per pin per vector) + zstd – `auto`
Chunk size sweep: **1 Mi vectors per chunk** was best (007 L19: 54.9x → 62.8x vs 16 Ki).

| config (full corpus) | size | ratio | vs zip | comp MB/s | decomp MB/s |
|---|---|---|---|---|---|
| `auto:3` | 758.6 MB | 30.7x | 2.3x | 1046 | 794 |
| `auto:9` | 751.9 MB | 31.0x | 2.3x | 813 | 788 |
| `auto:19` | 710.7 MB | 32.8x | 2.4x | 59 | 862 |

**Best: bit-packing.** This is the breakthrough: it doubles the ratio over plain zstd.
After packing, the zstd level matters little (L3 → L19 only adds 7%).

### 5. Transform implementation: numpy → C/OpenMP kernels
| kernel | numpy | C / OpenMP |
|---|---|---|
| analyse (symbol scan) | 413 MB/s | 7.3 GB/s |
| pack | 143 MB/s | 11.7 GB/s |
| unpack | 208 MB/s | 22.8 GB/s |
| transpose | 643 MB/s | 7.2 GB/s |
| untranspose | – | 13.6 GB/s |

**Best: C/OpenMP.** End to end, `auto:9` on the full corpus went from 82 / 146 MB/s
to 813 / 788 MB/s (about 10x faster, identical output).

### 6. Integrity checksum
| hash | MB/s |
|---|---|
| sha256 | 1843 |
| crc32 (zlib) | 1336 |
| **xxh3-128** | **21283** |

**Best: xxh3-128**: 11x faster than SHA-256, so verification costs almost nothing.

### 7. Thread scaling (file 003, 2.3 GB, L9)
| threads | 1 | 2 | 4 | 8 | 12 | 16 | 20 |
|---|---|---|---|---|---|---|---|
| raw zstd comp MB/s | 46 | 87 | 130 | 170 | 176 | 177 | 176 |
| bitpack comp MB/s | 541 | 663 | **977** | 934 | 974 | 922 | 875 |
| bitpack decomp MB/s | 742 | 766 | **933** | 796 | 825 | 831 | 775 |

**Best: 4 threads.** Bitpack on one thread is already 12x faster than plain zstd
(zstd only sees 1/8 of the data). Beyond 4 threads, speed stops improving
because a single zstd frame decodes on one thread.

### 8. Ternary packing (3⁵ = 243 ≤ 256 → 5 symbols per byte)
| config (full corpus) | size | ratio | vs zip | comp MB/s | decomp MB/s |
|---|---|---|---|---|---|
| `t5:9` (generic stream) | 1.2 GB | 18.7x | 1.4x | 587 | 845 |
| `t5row:9` (one alphabet per file) | 1.2 GB | 19.2x | 1.4x | 467 | 910 |
| `t5col:9` (ternary for every pin) | 838.0 MB | 27.8x | 2.0x | 657 | 938 |
| **`mixed:9`** (0 / 1 / 1.58 bits per pin) | **752.5 MB** | **31.0x** | **2.3x** | **931** | **988** |

**Best: `mixed`.** Pure ternary wastes bits on 2-symbol pins (1.58 bits vs 1),
so it loses to bit-packing. `mixed` uses binary for 2-symbol pins, ternary only for
3-symbol pins and 0 bits for constant pins. It ties bitpack overall and is
6–8% smaller on the two `H/L/X` files (001, 015).

### 9. Best-of hybrid (`best`): try `auto` and `mixed`, keep the smaller one
| config | size | ratio | comp MB/s | decomp MB/s |
|---|---|---|---|---|
| `best:3` | 758.3 MB | 30.7x | 650 | 744 |
| `best:9` | 751.7 MB | 31.0x | 447 | 747 |
| `best:19` | **709.0 MB** | **32.9x** | 28 | 892 |

**Best: not worth it.** It is the smallest output of all, but only 0.05% smaller than `mixed:19`
while compressing 2x slower (it encodes everything twice). `mixed` alone gets nearly all of the gain.

### 10. Ideas from the "split bit-planes" report → `planes` (container v3)
Following the report's own advice, every idea was **measured on the real corpus first**
(`tools/recon.py` → `results/recon.md`, `tools/explore_v3.py`):

| report idea | measured here | built? |
|---|---|---|
| Bit-planes instead of 2-bit symbols | pins are already 1 bit; only 160 H/L/X pins (36 KB) → mask + value planes | yes |
| XOR delta / period-aligned XOR | −0.06% | no |
| Run lengths for slow pins, clock descriptors | slow + periodic pins = 0.03% of the output | no |
| **Alias records for duplicate pins** | **38% of all pins are exact copies** (multi-site) | **yes** |
| **Longer per-pin context** | whole-file pin series vs 1 Mi chunks: **−5 to −6%** | **yes** |
| **Independent frames + index** | pins compress independently with no loss → parallel frames | **yes** |
| zstd window 2³⁰–2³¹, cross-file dedup | 0% (no long-range or cross-file repeats) | no |
| **Stronger back end (xz)** | 2–11% smaller than zstd −19 on real pin streams | **yes (archive tier)** |

Where the bytes are: dense pins = **99.97%** of the compressed output, so ideas aimed at
slow, periodic or constant pins cannot move the ratio on this corpus.

| config (full corpus, same session) | size | ratio | vs zip | comp MB/s | decomp MB/s |
|---|---|---|---|---|---|
| `mixed:9` (previous) | 752.5 MB | 31.0x | 2.3x | 901 | 717 |
| **`planes:9`** | **738.6 MB** | **31.6x** | 2.3x | **1037** | **945** |
| `mixed:19` (previous) | 709.4 MB | 32.9x | 2.4x | 48 | 841 |
| **`planes:19`** | **700.6 MB** | **33.3x** | 2.4x | **309** | **1030** |
| **`planesxz:6`** | **667.8 MB** | **34.9x** | **2.6x** | 257 | 808 |

**Best: `planes`.** At the same level it is 1–2% smaller, 15% to 6.4x faster to compress
and 22–32% faster to decompress. With xz frames it is **6% smaller than the previous best
while compressing 5.4x faster**. Gains are largest on multi-site files (009/024/025/026:
−5 to −6% at L9/L19, −17% with xz). Full write-up: `results/IDEAS.md` §10.

---

## Overall ranking (all full-corpus configs, 29 files, 22.8 GB, all bit-exact)

Rank 1 = best (of 23). Each config uses its latest full-corpus run.

| config | size | ratio | vs .pat zip | comp MB/s | decomp MB/s | size rank | comp rank | decomp rank |
|---|---|---|---|---|---|---|---|---|
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
| `raw:9` | 1.53 GB | 14.9x | 1.1x | 204 | 617 | 18 | 19 | 23 |
| `mixed:none` | 2.64 GB | 8.6x | 0.6x | 2000 | 1062 | 19 | 2 | 2 |
| `auto:none` | 2.82 GB | 8.1x | 0.6x | 1906 | 996 | 20 | 4 | 6 |
| `t5col:none` | 4.51 GB | 5.1x | 0.4x | 1733 | 1039 | 21 | 5 | 4 |
| `t5row:none` | 4.68 GB | 4.9x | 0.4x | 1970 | 1095 | 22 | 3 | 1 |
| `t5:none` | 5.14 GB | 4.4x | 0.3x | 2615 | 1039 | 23 | 1 | 3 |

### Winner per aspect
| aspect | winner | runner-up | comment |
|---|---|---|---|
| Smallest output | `planesxz:9` (667.0 MB) | `planesxz:6` (667.8 MB) | 0.1% apart; `:6` compresses 44% faster |
| Smallest pure-zstd output | **`planes:19`** (700.6 MB) | `best:19` (709.0 MB) | and 11x faster to compress than `best:19` |
| Fastest compression | `t5:none` (2615 MB/s) | `mixed:none` (2000 MB/s) | packing only, bigger than zip, so not usable |
| Fastest compression that beats zip | **`planes:3`** (1496 MB/s) | `mixed:3` (1254 MB/s) | 30.9x |
| Fastest decompression | `t5row:none` (1095 MB/s) | `mixed:none` (1062 MB/s) | bigger than zip |
| Fastest decompression that beats zip | **`planes:19`** (1030 MB/s) | `planes:3` (996 MB/s) | |
| Worst | `raw:9` | – | barely beats zip, slow to compress |

---

## 🏆 Best overall: `planesxz:6`

**667.8 MB, 34.9x, 2.6x smaller than today's `.pat` files**: the smallest output of all
(`planesxz:9` is only 0.1% smaller and 30% slower). Against the previous best (`mixed:19`)
it is **6% smaller and compresses 5.4x faster (257 vs 48 MB/s)** with about the same
decompression speed (808 MB/s). The trick: xz is slow, but it only sees the packed,
de-duplicated bit-planes (1/8 to 1/24 of the original bytes), and the frames run on all cores.

If the solution must be **pure zstd**, the winner is **`planes:19`**: 700.6 MB, 33.3x,
2.4x vs zip, the **fastest decompression of any config that beats zip (1030 MB/s)**, and
6.4x faster to compress than `mixed:19`.

## ⚖️ Best balanced: `planes:9`

**738.6 MB, 31.6x, 2.3x smaller than zip, > 1 GB/s compression, ~950 MB/s decompression.**

- vs plain zstd: **2.1x smaller, 5x faster to compress, 1.5x faster to decompress**.
- vs the previous balanced pick (`mixed:9`): 1.8% smaller, 15% faster to compress, 32% faster to decompress.
- vs the smallest (`planesxz:6`): 11% bigger, but 4x faster to compress.
- `planes:3` is the choice when speed matters most (+2% size, 1.5 GB/s compression).

### How `planes` works
1. **Full-length pin-major bit-planes.** `Vectors.vec` is cut into segments of 16 Mi vectors
   (the whole file for 27/29 files). Inside a segment, every pin's waveform is one
   contiguous bit stream (1 bit/vector). Newlines aren't stored.
2. **Pin aliasing.** Per segment, each binary pin is stored, or marked all-0, all-1, or
   "same bits as pin j" (exact byte comparison). That removes the 38% duplicated pins of
   multi-site patterns, and complementary pins too (every stream starts with bit 0).
3. **H/L/X pins** become a mask plane (X) plus a value plane (H/L).
4. **Independent frames.** The streams are grouped into ~2 MiB frames, each compressed
   as its own zstd (or xz) frame on all cores, listed in an index. The decoder
   decompresses frames in parallel and pipelines unpacking, hashing and writing.
5. **Integrity.** xxh3-128 over the decoded bytes and every metadata byte; any flipped
   byte anywhere in the file is detected (the test suite flips every byte).

Byte-level format: [`docs/FORMAT.md`](docs/FORMAT.md) §9.

### How `mixed` (the previous v2 method) works
1. **Pin-major layout.** `Vectors.vec` is cut into chunks of 1 Mi vectors, and inside each chunk
   every pin's waveform is stored contiguously.
2. **Per-pin bit width**, recorded in the header together with the pin's symbols:
   constant pin → **0 bits**; 2 symbols → **1 bit/vector**; 3 symbols →
   **5 symbols per byte** (≈1.58 bits). Newlines aren't stored; they are regenerated from the line width.
   This step alone: 22.8 GB → 2.6 GB.
3. **zstd** (multi-threaded, long-distance matching, 128 MiB window): 2.6 GB → 752.5 MB.
4. **Integrity**: xxh3-128 of every original member, checked by the decoder,
   which refuses to return wrong data. Any member that isn't a clean grid
   (ragged lines, CRLF, XML, …) falls back to the generic `t5` / `raw` modes.

The transform runs in C/OpenMP at 7–23 GB/s, so zstd is the only slow part.
`Program.sprg` (`genVec` / `repeat`) is left untouched: the tester sees exactly the same pattern.

Byte-level format: [`docs/FORMAT.md`](docs/FORMAT.md).

---

## Repository layout

```
patzstd/codec.py     codec / .pzst v2 container
patzstd/planes.py    planes / planesxz: container v3 (bit-planes, aliasing, parallel frames)
patzstd/fast.py      ctypes wrappers for the C kernels
patzstd/kernels.c    C/OpenMP kernels (bitpack, transpose, ternary); built on first use
patzstd/ternary.py   ternary 3^5 packing + Python/numpy reference versions
docs/FORMAT.md       byte-level specification of every mode
compress.py          CLI: .pat / folder  -> .pzst
decompress.py        CLI: .pzst          -> folder or .pat
testbench.py         dataset benchmark + bit-exact verification
tests/               unit tests (codec: 20, ternary: 29, planes: 14)
tools/               recon.py (E0 per-pin analysis), explore_v3.py (report experiments),
                     ternary_explore.py (ternary escape-overhead study)
results/             every benchmark (CSV + Markdown) and IDEAS.md (full experiment log)
```

The pattern data (`data/`, 27 GB) is not in the repository.

## Setup

Requirements: Python ≥ 3.9 and `gcc` with OpenMP (the kernels are compiled automatically on first use).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install zstandard numpy xxhash
```

Put the original files in `data/pat_original/NNN.pat`. The test bench reads the
unpacked copies from `data/extracted/NNN.pat/` by default (`--source pat` reads the zips directly).

## Usage

```bash
# recommended (balanced)
./compress.py data/pat_original/*.pat --mode planes -l 9     # -> out/NNN.pzst
# smallest, pure zstd
./compress.py data/pat_original/*.pat --mode planes -l 19
# smallest overall (xz archive tier); --frame-mib 8 = another 0.6-1.8%, 2x slower
./compress.py data/pat_original/*.pat --mode planesxz -l 6
# plain zstd baseline
./compress.py data/pat_original/003.pat --mode raw -l 9

./decompress.py out/*.pzst             # -> restored/NNN.pat/ (folders, members byte-identical)
./decompress.py out/*.pzst --as-pat    # -> restored/NNN.pat  (zip rebuilt)

python -m unittest discover -s tests -v                      # unit tests
./testbench.py --quick                                       # small files only
./testbench.py --configs raw:9 planes:3 planes:9 planes:19 planesxz:6   # full corpus
tools/recon.py                                               # per-pin analysis
```

Modes: `planes`, `planesxz` (v3), `auto` (bitpack / transpose / raw), `mixed`, `best`,
`bitpack`, `transpose`, `t5`, `t5row`, `t5col`, `raw`. Levels: 1–22 (`planesxz`: xz preset 0–9)
or `none` (packing only). The decoder reads v2 and v3 files.

Note: decompressed **members** are byte-identical to the originals. With `--as-pat`
the zip container is rebuilt, so the `.pat` file's own bytes (timestamps,
deflate output) differ, but its contents are identical.

## Next ideas (not tried yet)
- A context-modelling bit coder (JBIG-style template over the previous vectors of the same pin
  and its neighbours) as an archive tier: zstd already beats the order-1 floor by 1.4x, so
  the remaining structure is higher-order; decode would be MB/s, not GB/s.
- A C decoder writing straight into tester memory (pin-major frames already match a per-pin layout).
- Restore `genVec` / `repeat` loops from repeated vector blocks.
