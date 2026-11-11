# CLAUDE.md

## Rules
- Do not search or read files outside this folder unless the user explicitly allows it.

## Current focus
- Working in `tests/Visualization/` on the data in `tests/001-contents/`. Local goals and findings are tracked in `tests/Visualization/CLAUDE.md`.
- zstd baseline: `tests/Compression/vcompress.c`. Run it as `vcompress.exe <level> [in.vec] [outdir]`. It writes `vector_<level>.compr` and prints the ratio and speeds, and the round-trip is verified. It links the WinLibs `libzstd.dll` (1.5.7), with a copy next to the exe.

- Drive/read split + zstd: `tests/Split/split.c` (details and results in its `CLAUDE.md`). On 001 it is 1.3x smaller than whole-file zstd.
- Git branch `claude-tries`: `tests/ClaudeTries/` (details in its `CLAUDE.md`). **pack** (per-column alphabet + bit planes, then zstd) is 2.15x smaller than zstd L9 across all 29 sample archives (24.4 GB, byte-exact) and compresses 3x faster. The end files are in `results/` (git-ignored).
- Branch "DDNF": logic-minimization research in `tests/scientific-optimization/`. The survey and assessment are in `research.md`; goals are in the local `CLAUDE.md`.

## Challenge: compress ATE pattern vector data (Advantest, NextSemi Hackathon)
Source: `Chellenge/NextSemi Hackathon_Advantest_Challenge.pdf`

### Problem
- ATE (automatic test equipment) drives a chip (DUT) with input stimulus (`0`/`1`) and compares its outputs against expected `L`/`H` values, cycle by cycle. These per-pin, per-cycle values are stored as **pattern vector files** (`.pat`).
- Most of this data is SCAN test data from DFT tooling. Its size grows with transistor count, so it grows exponentially: up to ~10 TB raw per tester, ~0.5 TB after compression.
- **Baseline: the data is already compressed with zstd. Results must beat zstd.**
- Why it matters: file-share storage, network transfer (sometimes 100 Mbit), workstation SSD space, and download time into instrument DRAM.

### Goal
Find and prototype compression methods that exploit the structure of pattern data, not just generic byte compression.

### Deliverables
1. Prototype implementations (any language).
2. Benchmarks for **every** idea tried: compression ratio vs. zstd, compression speed, decompression speed, and how the speeds scale with input size.
3. A list of approaches that did not work, with numbers.

### Data
- Sample corpus: `.pat` files (`001`–`029`) in `../hackathon/hackathon/`. This is outside this folder, so ask before reading it.
- A larger corpus will be handed out at the 30h mark. Final results are measured on it, so the code must handle bigger inputs.
- Format docs (V93000 SmarTest help, "genvec") need an Advantest login. Treat them as unavailable unless the user supplies them, and work out the format from the samples.

### Scoring (max 30)
| Criterion | Weight |
|---|---|
| Compression results: ratio vs. zstd plus speed and scaling, on the big corpus | **2x** |
| Technical feasibility: works, measured, reproducible, honest about limits | 1x |
| Innovation | 1x |
| Market potential | 1x |
| Business viability | 1x |

### Hard requirements
- Decompression must be **lossless**: the decompressed `.pat` file must be byte-for-byte identical to the input (confirmed by the user). Check this in every benchmark, for example with a hash or `cmp`.
- Always report against a zstd baseline on the same input.
