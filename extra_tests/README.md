# extra_tests

Sandbox for additional test runs (started 2026-11-12).
Existing results/, work/, tests/ and logs stay where they are — nothing was moved,
and `patzstd/` / `patamd/` are untouched (the code here imports nothing from them).

- scripts/  new test / bench scripts for this round
- results/  CSV + markdown outputs of these runs
- work/     temporary compressed outputs
- logs/     run logs

## `xt` codec family (round 1: research-note principles)

Code: `scripts/xt_kernels.c` (C/OpenMP + libzstd), `scripts/xtcodec.py`, `scripts/xt_bench.py`.
A config is `LAYOUT:BACKEND`.

| layout | principle | what it does |
|---|---|---|
| `raw` | – | file as is |
| `tr8` | transpose (AoA → SoA) | per-pin byte streams, 1 byte/symbol, cache-blocked 256-row tiles |
| `pp`  | bit packing + transpose | per-pin bit planes: 1 bit/vector (2 symbols), 2 planes (3–4 symbols), 0 (constant) |
| `ppd` | XOR along time | `pp` + bit transitions inside each plane (x_t ^ x_{t-1}) |
| `rx`  | XOR / delta between rows | row-major bit rows, row[n] ^ row[n-1]; parallel prefix-XOR decode |

| backend | principle |
|---|---|
| `zstd9`, `zstd19` | plain zstd, one frame (`raw:zstd9` = the reference) |
| `zstd9L`, `zstd19L` | zstd `--long=31`: LDM, window = whole stream (up to 2 GiB) |
| `zstd9R`, `zstd3R` | RAP-style independent 16 MiB frames + index, OpenMP decode straight into the output |
| `bz3` | BWT (bzip3), 64 MiB blocks, multi-threaded |
| `br9` | brotli q9, lgwin 24, 64 MiB blocks in parallel |
| `lz4hc`, `lz4` | LZ4 HC-12 / LZ4 fast, 16 MiB blocks in parallel |
| `dfl9` | deflate (zlib) 9, 16 MiB blocks in parallel |

All decoders write into a preallocated mmap buffer with `MADV_HUGEPAGE`.
Not testable on this machine: AOCL-zstd / AOCL-LZ4 and AVX-512 (Intel i7-1370P, AVX2 only).

Note on the reference: `raw:zstd9` here is plain zstd -9 (default 8 MiB window).
The older `raw:9` in `../results/` used a 128 MiB window and is ~11% smaller.

Run (venv of the challenge repo; lz4 is vendored in `scripts/_pydeps`, not in git: `pip install --target scripts/_pydeps lz4`):

```bash
PY=../../Semicon_europe_challenge/.venv/bin/python
$PY scripts/xt_bench.py --files 006 007 --tag smoke
$PY scripts/xt_bench.py --tag full
```

Every row is a verified round trip (memcmp against the original Vectors.vec).

## `xt2` round 2: block-indexed split-stream container (`bk`)

Code: `scripts/xt2_kernels.c`, `scripts/xt2codec.py`, `scripts/xt2_bench.py` (`--profile`, `--threads 1`),
`scripts/xt2_param_sweep.py`. Configs `raw:z<L>[L<wlog>]` and `bk<R|A>:<L>[l][x][r][g]` (see `xt2codec.py`).
Results: `results/XT2_REPORT_20261112.md`. Best: `bkA:19lg` 732.9 MB (2.38x vs zstd -9), `bk4:3g` 794.1 MB at 1485 MB/s.

```bash
$PY scripts/xt2_bench.py --configs raw:z9 bkA:19lg bk4:9g bk4:3g --tag full
taskset -c 4 $PY scripts/xt2_bench.py --threads 1 --files 007 014 --configs raw:z9 bk4:9g --tag st
```
