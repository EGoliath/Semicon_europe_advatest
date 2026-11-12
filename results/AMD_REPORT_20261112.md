# Codec benchmark vs plain zstd -9 (2026-11-12)

Lossless compression of the 29 SmarTest `.pat` files (24.4 GB = 22.8 GiB uncompressed).
Every config below round-tripped **bit-exact on 29/29 files** (xxh3-128 checked).

> **Measured on the Intel development laptop, not on an AMD EPYC.**
> Machine: 13th Gen Intel Core i7-1370P (14 physical cores / 20 threads, one 24 MiB L3),
> 30 GB RAM, AVX2 kernels. The `amd_*` configs are the versions tuned for EPYC (core pinning per
> CCD, AVX2/AVX-512 builds); on this laptop they run as ordinary multi-core code, which is why they
> match the originals. Their EPYC speed still has to be measured on EPYC hardware.
> Sizes do not depend on the machine; times do.

## 1. Summary

| goal | pick | size vs zstd-9 | comp speed vs zstd-9 | decomp speed vs zstd-9 |
|---|---|---|---|---|
| Smallest file | `amd_pcm_mt:3` | **-59.9%** | -76% | -91% |
| Small and fast to decompress | `planesxz:6` / `amd_planesxz_mt:9` | -57.3% / -57.4% | +17% / +1% | +39% / +36% |
| Best all-round (zstd only) | `planes:19` | -55.2% | +43% | **+66%** |
| Fastest compression | `planes:9` | -52.8% | **+453%** | +61% |

- Every config is **52–60% smaller** than plain zstd -9.
- `planes:19`, `planesxz:6` and `planes:9` are smaller **and** faster than zstd -9 in both directions.
- The new `pcm` coder is the smallest, but about 11x slower to decompress than zstd -9.
- `amd_*` copies give identical sizes to the originals (same format idea, same back end); speeds are within noise on this laptop.

## 2. Full results vs zstd -9

Baseline `raw:9` = the file bytes compressed by zstd level 9, no transform:
**1640.0 MB, 14.9x, compress 117 s (210 MB/s), decompress 42 s (583 MB/s).**

Speed = original MB / seconds. Size %: negative = smaller (better).
Time %: negative = faster (better). Speed %: positive = faster (better).

| # | config | size | ratio | size vs zstd-9 | comp time | comp time vs zstd-9 | comp MB/s | comp speed vs zstd-9 | decomp time | decomp time vs zstd-9 | decomp MB/s | decomp speed vs zstd-9 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `amd_pcm_mt:3` | 657.8 MB | 37.2x | -59.9% | 495 s | +324% | 49 | -76% | 482 s | +1049% | 51 | -91% |
| 2 | `amd_pcm_mt:2` | 659.0 MB | 37.1x | -59.8% | 397 s | +240% | 62 | -71% | 444 s | +959% | 55 | -91% |
| 3 | `amd_planesbwt_mt:1` | 687.3 MB | 35.6x | -58.1% | 51 s | -56% | 477 | +127% | 56 s | +33% | 438 | -25% |
| 4 | `planesxz:9` | 699.4 MB | 34.9x | -57.4% | 126 s | +8% | 194 | -7% | 30 s | -28% | 813 | +40% |
| 5 | `amd_planesxz_mt:9` | 699.4 MB | 34.9x | -57.4% | 116 s | -1% | 211 | +1% | 31 s | -26% | 792 | +36% |
| 6 | `planesxz:6` | 700.2 MB | 34.9x | -57.3% | 100 s | -14% | 244 | +17% | 30 s | -28% | 810 | +39% |
| 7 | `amd_planesxz_mt:6` | 700.2 MB | 34.9x | -57.3% | 100 s | -14% | 244 | +16% | 31 s | -26% | 784 | +34% |
| 8 | `planes:19` | 734.6 MB | 33.3x | -55.2% | 82 s | -30% | 300 | +43% | 25 s | -40% | 967 | +66% |
| 9 | `amd_planes_mt:19` | 734.6 MB | 33.3x | -55.2% | 80 s | -31% | 304 | +45% | 26 s | -37% | 931 | +60% |
| 10 | `best:19` | 743.4 MB | 32.9x | -54.7% | 1024 s | +778% | 24 | -89% | 34 s | -19% | 722 | +24% |
| 11 | `amd_best_mt:19` | 743.4 MB | 32.9x | -54.7% | 1027 s | +781% | 24 | -89% | 33 s | -21% | 739 | +27% |
| 12 | `mixed:19` | 743.8 MB | 32.9x | -54.6% | 536 s | +360% | 46 | -78% | 33 s | -22% | 750 | +29% |
| 13 | `amd_mixed_mt:19` | 743.8 MB | 32.9x | -54.6% | 534 s | +358% | 46 | -78% | 32 s | -24% | 767 | +32% |
| 14 | `auto:19` | 745.2 MB | 32.8x | -54.6% | 494 s | +324% | 49 | -76% | 38 s | -9% | 641 | +10% |
| 15 | `amd_auto_mt:19` | 745.2 MB | 32.8x | -54.6% | 493 s | +323% | 50 | -76% | 39 s | -6% | 623 | +7% |
| 16 | `planes:9` | 774.5 MB | 31.6x | -52.8% | 21 s | -82% | 1160 | +453% | 26 s | -38% | 936 | +61% |
| 17 | `amd_planes_mt:9` | 774.5 MB | 31.6x | -52.8% | 22 s | -81% | 1096 | +423% | 27 s | -36% | 913 | +57% |
| 18 | `best:9` | 788.2 MB | 31.0x | -51.9% | 46 s | -60% | 530 | +153% | 38 s | -10% | 651 | +12% |
| 19 | `amd_best_mt:9` | 788.9 MB | 31.0x | -51.9% | 49 s | -58% | 502 | +140% | 38 s | -10% | 650 | +11% |
| 20 | **`raw:9` (base)** | 1640.0 MB | 14.9x | 0% | 117 s | 0% | 210 | 0% | 42 s | 0% | 583 | 0% |

## 3. How `planes:19` works

The idea: **don't change the compressor, change what it sees.** A `.pat` file is mostly text that
plain zstd reads as characters. `planes` turns it into many small, very regular bit streams,
one per pin, and lets zstd compress those.

### 3.1 What is in a `.pat` file

`Vectors.vec` (about 99% of the data) is a grid: one line per vector (test cycle), one character per
pin, e.g. `0110X1...`. Each pin only ever uses 1–3 distinct symbols (`0/1`, `L/H`, sometimes `X`).
So a character costs 8 bits but carries about 1 bit of information. Plain zstd -9 has to discover
this through text matching, and only gets 14.9x.

### 3.2 The transform, step by step

```
 Vectors.vec (row = vector, column = pin)        planes (one bit stream per pin, whole file)

   vector 0:  0 1 1 0 X 1 ...                     pin 0: 0 0 0 0 1 1 1 1 ...   1 bit / vector
   vector 1:  0 1 1 1 X 1 ...      ───────►       pin 1: 0 0 0 0 0 0 ...       (all 0 -> 0 bits)
   vector 2:  1 1 0 1 L 1 ...                     pin 2: copy of pin 7        -> 0 bits
   vector 3:  1 1 0 0 H 1 ...                     pin 4: mask plane (is X?) + value plane (is H?)
      ...                                          ...
```

1. **Classify each pin** by how many distinct symbols it uses over the whole file:
   - 1 symbol: *constant*, stored only in the pin table (0 bits per vector);
   - 2 symbols: *binary*, 1 bit per vector;
   - 3 symbols (H/L/X): *ternary*, split into a **mask plane** (is this X?) and a **value plane**
     (is this H?), 2 bits per vector.
2. **Pin-major bit planes.** Bits are written per pin, along the time axis: pin 0's whole history,
   then pin 1's, and so on. Bit = "symbol differs from this pin's first symbol", so each stream starts
   with 0.
3. **Long context.** A pin's stream runs over a whole segment of 16 Mi vectors, which is the entire
   file for 27 of the 29 files. Measured: 5–6% smaller than cutting into 1 Mi-vector chunks,
   because repeating patterns that are far apart in time stay inside one stream.
4. **Pin aliasing (0 bits for repeats).** Because every stream starts with 0, a duplicate pin and an
   inverted pin (L/H mirror of 0/1) produce *identical bytes*. One dictionary lookup per pin finds
   them, and they are stored as "same as pin j". All-0 and all-1 pins are stored as a flag. About
   38% of the pins in this corpus are exact duplicates (multi-site testing), so this removes a lot.
5. **Frames by pin group.** The stored streams are concatenated into independent frames of about
   2 MiB (several pins each) and each frame is compressed separately with **zstd level 19**. Pins
   barely help each other (measured: no loss from splitting them), so many frames can be compressed
   and decompressed in parallel on all cores.
6. **Everything else** (XML headers, comments, other zip members) is stored as plain zstd frames
   (`zraw`).
7. **Integrity:** an xxh3-128 hash covers the original bytes and every metadata byte; decompression
   recomputes it and rejects any mismatch.

### 3.3 Why level 19 (and why it is still fast)

zstd level 19 uses the `btultra2` strategy (binary-tree match finder with optimal parsing). On 2 MiB
frames it uses a 2 MiB window, i.e. it sees the whole frame. Level 19 is normally slow, but here:
- the input is **8x smaller** than the text (1 bit instead of 8 per pin-vector) and duplicates are
  already removed, so zstd has much less to search;
- frames are independent, so all 14 cores work at once.

Result: 734.6 MB (-55.2% vs zstd -9), compress 300 MB/s, decompress **967 MB/s** (the fastest
decompression of all configs). Decompression is fast because zstd decoding is cheap at any level,
and the bit-to-character unpacking runs in a multi-threaded C kernel.

## 4. How `planesxz:9` / `amd_planesxz_mt:9` work

### 4.1 Same transform, different back end

`planesxz` uses **exactly the same planes transform** as section 3 (classification, bit planes,
aliasing, 2 MiB pin-group frames). The only change is step 5: each frame is compressed with
**xz / LZMA2 preset 9 extreme** (`-9e`) instead of zstd.

LZMA2 codes each match and literal with an **adaptive binary range coder** whose probabilities depend
on context (the previous bits, the position, the last match). zstd uses static Huffman/FSE tables per
block. On long, nearly-periodic bit streams, the adaptive model saves about **5% more** than zstd 19:
699.4 MB vs 734.6 MB (-57.4% vs zstd -9).

The price: LZMA decoding is serial bit by bit, so decompression is slower than zstd (about 800 vs
about 970 MB/s), and compressing at preset 9e is slower than zstd 19.

### 4.2 What the `amd_..._mt` copy adds

`amd_planesxz_mt:9` lives in `patamd/` (a copy; the original `patzstd/` is untouched). Same bytes in
the frames, so **the same size** (699.4 MB). Differences:

- **Container v4:** a codec byte per frame, so one file can mix back ends (zstd, xz, pcm, bzip3).
- **xz dictionary sized to the frame:** preset 9e normally allocates a 64 MiB dictionary
  (about 674 MiB of encoder memory) even for a 2 MiB frame. With 64 EPYC cores x 674 MiB that does not
  fit in memory, so the dictionary is cut to the frame size. Output is unchanged; memory per worker drops
  sharply.
- **`mt` CPU profile:** worker threads pinned round-robin over the L3 domains (CCDs on EPYC: each Zen 4
  CCD has its own 32 MB L3), physical cores first, then SMT siblings.
- **C kernels in three builds** (generic, AVX2, AVX-512); the best one the CPU supports is loaded.

On this laptop (one L3, 14 cores) the pinning has nothing to spread across, so `amd_planesxz_mt:9`
runs like `planesxz:9`: compress 211 vs 194 MB/s, decompress 792 vs 813 MB/s (within measurement
noise). The benefit of the CCD pinning can only be shown on an EPYC.

### 4.3 xz 6 vs xz 9

`planesxz:6` is only 0.8 MB bigger than `planesxz:9` (700.2 vs 699.4 MB) and compresses faster
(244 vs 194 MB/s). On these small frames the extra search of preset 9e finds almost nothing, so `:6`
is the better choice unless every byte counts.

## 5. Method and caveats

- **Corpus:** all 29 `.pat` files in `data/pat_original`, 24.4 GB uncompressed.
- **Size** = compressed `.pzst` bytes (MB = 10^6 bytes). Earlier notes quoting 667.8 "MB" for
  `planesxz:6` were MiB; it is the same 700.2 MB.
- **Times** = wall-clock totals over the 29 files, multi-core (all threads), from
  `testbench_amd.py`. Speed = original bytes / time.
- **Runs:** main results `results/bench_20261112_021818_amd_full_mt.csv`; baseline `raw:9` re-run the
  same day in `results/bench_20261112_044219_raw9_ref.csv`, together with `planesxz:6` as a drift
  check. That check gave decompression 30 s vs 31 s (same) and compression 100 s vs 91 s
  (about 10% run-to-run noise), so compression differences smaller than about 10% are not significant.
- **Single core:** a 13-file subset was also run with the `st` profile
  (`results/bench_20261112_042017_amd_subset_st.csv`): same sizes, about 3x slower (`pcm` about 27
  MB/s, `planesxz` about 80 MB/s compress).
- **Hardware:** Intel i7-1370P laptop (see top). The EPYC-specific gains of the `amd_*` configs are
  not measured yet.
