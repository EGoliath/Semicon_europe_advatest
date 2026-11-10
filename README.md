# Semicon Europe × Advantest challenge – lossless compression of V93000 pattern files

Lossless compression of SmarTest `.pat` pattern files with **zstd**, after a
pattern-aware transform: **each pin's waveform is stored with only the bits it needs**.
Every result below was checked for an exact bit-for-bit round trip (xxh3-128 inside
the container, plus an independent SHA-256 check in the test bench).

## TL;DR

| | config | size (22.8 GB corpus) | ratio | vs today's `.pat` zip | compress | decompress |
|---|---|---|---|---|---|---|
| Today's format | `.pat` zip (deflate) | 1.7 GB | 13.4x | 1.0x | – | – |
| Plain zstd (baseline) | `raw:9` | 1.5 GB | 14.9x | 1.1x | 227 MB/s | 746 MB/s |
| 🏆 **Best overall (smallest practical output)** | **`mixed:19`** | **709.4 MB** | **32.9x** | **2.4x** | 53 MB/s | **966 MB/s** |
| ⚖️ **Best balanced** | **`mixed:9`** | **752.5 MB** | **31.0x** | **2.3x** | **879 MB/s** | **873 MB/s** |
| ⚡ Fastest config that still beats zip | `mixed:3` | 758.7 MB | 30.7x | 2.3x | 1254 MB/s | 897 MB/s |

Config names are `mode:zstd-level` (`none` = packing only, no zstd).
Measured on an Intel i7-1370P (14 cores / 20 threads, 30 GB RAM, RHEL 9,
Python 3.9, zstandard 0.25 / libzstd 1.5.7), on all 29 `.pat` files (22.8 GB uncompressed).
Speeds vary by ±15% from run to run. Sizes are exact.

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

---

## Overall ranking (all full-corpus configs, 29 files, 22.8 GB, all bit-exact)

Rank 1 = best. Each config uses its latest (fastest-code) run.

| config | size | ratio | vs .pat zip | comp MB/s | decomp MB/s | size rank | comp rank | decomp rank |
|---|---|---|---|---|---|---|---|---|
| `best:19` | 709.0 MB | 32.9x | 2.4x | 28 | 892 | **1** | 18 | 10 |
| `mixed:19` | 709.4 MB | 32.9x | 2.4x | 53 | 966 | **2** | 17 | 6 |
| `auto:19` | 710.7 MB | 32.8x | 2.4x | 59 | 862 | **3** | 16 | 12 |
| `best:9` | 751.7 MB | 31.0x | 2.3x | 447 | 747 | 4 | 14 | 16 |
| `auto:9` | 751.9 MB | 31.0x | 2.3x | 813 | 788 | 5 | 9 | 15 |
| `mixed:9` | 752.5 MB | 31.0x | 2.3x | 879 | 873 | 6 | 8 | 11 |
| `best:3` | 758.3 MB | 30.7x | 2.3x | 650 | 744 | 7 | 11 | 18 |
| `auto:3` | 758.6 MB | 30.7x | 2.3x | 1046 | 794 | 8 | 7 | 14 |
| `mixed:3` | 758.7 MB | 30.7x | 2.3x | 1254 | 897 | 9 | 6 | 9 |
| `t5col:9` | 838.0 MB | 27.8x | 2.0x | 657 | 938 | 10 | 10 | 7 |
| `t5row:9` | 1.2 GB | 19.2x | 1.4x | 467 | 910 | 11 | 13 | 8 |
| `t5:9` | 1.2 GB | 18.7x | 1.4x | 587 | 845 | 12 | 12 | 13 |
| `raw:9` (plain zstd) | 1.5 GB | 14.9x | 1.1x | 227 | 746 | 13 | 15 | 17 |
| `mixed:none` | 2.6 GB | 8.6x | 0.6x | 2000 | 1062 | 14 | 2 | 2 |
| `auto:none` | 2.8 GB | 8.1x | 0.6x | 1906 | 996 | 15 | 4 | 5 |
| `t5col:none` | 4.5 GB | 5.1x | 0.4x | 1733 | 1039 | 16 | 5 | 3= |
| `t5row:none` | 4.7 GB | 4.9x | 0.4x | 1970 | 1095 | 17 | 3 | **1** |
| `t5:none` | 5.1 GB | 4.4x | 0.3x | 2615 | 1039 | 18 | **1** | 3= |

### Winner per aspect
| aspect | winner | runner-up | comment |
|---|---|---|---|
| Smallest output | `best:19` (709.0 MB) | `mixed:19` (709.4 MB) | 0.05% apart; `mixed:19` compresses 2x faster |
| Fastest compression | `t5:none` (2615 MB/s) | `mixed:none` (2000 MB/s) | packing only, bigger than zip, so not usable |
| Fastest compression that beats zip | **`mixed:3`** (1254 MB/s) | `auto:3` (1046 MB/s) | 30.7x |
| Fastest decompression | `t5row:none` (1095 MB/s) | `mixed:none` (1062 MB/s) | bigger than zip |
| Fastest decompression that beats zip | **`mixed:19`** (966 MB/s) | `t5col:9` (938 MB/s) | |
| Worst | `raw:9` | – | barely beats zip, slow to compress |

---

## 🏆 Best overall: `mixed:19`

The smallest output that is still practical: **709.4 MB, 32.9x, 2.4x smaller than
today's `.pat` files**, with the **fastest decompression of any config that beats zip (966 MB/s)**.
`best:19` is 0.4 MB smaller but compresses at half the speed, so `mixed:19`
is the real winner when size is what counts. Compression (53 MB/s) is slow, but it runs
only once per pattern, while the pattern is decompressed many times on the tester.

## ⚖️ Best balanced: `mixed:9`

**752.5 MB, 31.0x, 2.3x smaller than zip, about 880 MB/s in both directions.**

- vs plain zstd: **2x smaller and about 4x faster to compress** (zstd sees 8x less data, and it is better organised).
- vs the smallest (`best:19`): only 6% bigger, but **31x faster** to compress
  (the 23 GB corpus in about 26 s instead of about 14 min).
- vs `auto:9`: same size overall, slightly faster, and 6–8% smaller on `H/L/X` files.
- `mixed:3` is an equally good choice when speed matters most (+1% size, +40% compression speed).

### How `mixed` works
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
patzstd/codec.py     codec / .pzst container
patzstd/fast.py      ctypes wrappers for the C kernels
patzstd/kernels.c    C/OpenMP kernels (bitpack, transpose, ternary); built on first use
patzstd/ternary.py   ternary 3^5 packing + Python/numpy reference versions
docs/FORMAT.md       byte-level specification of every mode
compress.py          CLI: .pat / folder  -> .pzst
decompress.py        CLI: .pzst          -> folder or .pat
testbench.py         dataset benchmark + bit-exact verification
tests/               unit tests (codec: 20, ternary: 29)
tools/               ternary escape-overhead study
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
./compress.py data/pat_original/*.pat --mode mixed -l 9      # -> out/NNN.pzst
# smallest
./compress.py data/pat_original/*.pat --mode mixed -l 19
# plain zstd baseline
./compress.py data/pat_original/003.pat --mode raw -l 9

./decompress.py out/*.pzst             # -> restored/NNN.pat/ (folders, members byte-identical)
./decompress.py out/*.pzst --as-pat    # -> restored/NNN.pat  (zip rebuilt)

python -m unittest discover -s tests -v                      # unit tests
./testbench.py --quick                                       # small files only
./testbench.py --configs raw:9 mixed:3 mixed:9 mixed:19      # full corpus
```

Modes: `auto` (bitpack / transpose / raw), `mixed`, `best`, `bitpack`, `transpose`,
`t5`, `t5row`, `t5col`, `raw`. Levels: 1–22 or `none` (packing only).

Note: decompressed **members** are byte-identical to the originals. With `--as-pat`
the zip container is rebuilt, so the `.pat` file's own bytes (timestamps,
deflate output) differ, but its contents are identical.

## Next ideas (not tried yet)
- Write each chunk as an independent zstd frame, so decompression can run in parallel (it currently stops scaling at 4 threads).
- Store duplicated pin columns once (multi-site patterns repeat the same pin groups).
- Detect repeating periods (clocks) before zstd.
- A zstd dictionary trained across the corpus; windows larger than 128 MiB.
- Restore `genVec` / `repeat` loops from repeated vector blocks.
