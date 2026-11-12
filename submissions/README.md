# Submission packages

Each folder is a self-contained codec: copy or download one folder (or its zip in `dist/`), then
`pip install -r requirements.txt` and run `compress.py` / `decompress.py` / `evaluate.py`.
All packages share the same command line, so the team can evaluate them the same way.

Numbers: full corpus (29 files, 24.44 GB), 20 threads, i7-1370P, every result verified bit-exact 29/29.
Size vs plain zstd -9 (1740.7 MB): positive = smaller. Speeds vs zstd -9 measured by the same bench script: positive = faster.

| package | config | size | ratio | size vs zstd -9 | comp MB/s | comp vs zstd -9 | decomp MB/s | decomp vs zstd -9 | best for |
|---|---|---|---|---|---|---|---|---|---|
| [`01_pcm`](01_pcm/) | `amd_pcm_mt:3` | 657.8 MB | 37.2x | +62.2% | 49 | -77% | 51 | -91% | smallest file |
| [`02_planesbwt`](02_planesbwt/) | `amd_planesbwt_mt:1` | 687.3 MB | 35.6x | +60.5% | 477 | +127% | 438 | -25% | small + fast compress |
| [`03_planesxz`](03_planesxz/) | `planesxz:6` | 700.2 MB | 34.9x | +59.8% | 270 | +29% | 781 | +34% | small + decomp faster than zstd |
| [`04_pp_zstd_long`](04_pp_zstd_long/) | `pp:zstd19L` | 732.5 MB | 33.4x | +57.9% | 73 | -86% | 3197 | +164% | fastest decompression |
| [`05_bk_container`](05_bk_container/) | `bkA:19lg` | 732.9 MB | 33.3x | +57.9% | 247 | -52% | 2213 | +78% | balanced (parallel) |
| [`06_planes`](06_planes/) | `planes:19` | 734.6 MB | 33.3x | +57.8% | 300 | +43% | 967 | +66% | pure zstd, tunable level |
| [`00_zstd9_baseline`](00_zstd9_baseline/) | `plain zstd -9` | 1740.7 MB | 14.0x | +0.0% | 517 | +0% | 1245 | +0% | reference |

Full ranking of all 60 tested configs: [`../extra_tests/results/TOP25_ALL_TESTS_20261112.md`](../extra_tests/results/TOP25_ALL_TESTS_20261112.md).

## Evaluate one package

```bash
cd 05_bk_container
pip install -r requirements.txt
python evaluate.py /path/to/pat_files/          # writes eval_<package>_<time>.md/.csv in the current folder
```

## Layout

- `0N_*/` — the packages. `01`, `02` contain a copy of `patamd/`; `03`, `06` a copy of `patzstd/`;
  `00`, `04`, `05` use the new PXT1 container (`patio.py`). Nothing outside `submissions/` was changed.
- `_shared/` — sources of the files copied into every package (`evaluate.py`, PXT `patio.py` and CLIs).
- `build_dist.sh` — re-syncs the shared files and rebuilds `dist/<package>.zip`.
- `dist/` — one zip per package, ready to download / send.
