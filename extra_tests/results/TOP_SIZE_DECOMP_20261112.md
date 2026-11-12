# Top configs: smallest size + fastest decompression (full corpus, 29 files, all threads, all verified 29/29)

Decompression speed is also shown relative to the zstd -9 baseline *of the same harness*, because the harnesses differ:
old `results/` harness raw:9 = 583 MB/s, xt round 1 = 1211 MB/s, xt2 round 2 = 1245 MB/s.
Size is compared with plain zstd -9 (1740.7 MB).

| # | config | source | size | vs zstd -9 | decomp MB/s | decomp vs own zstd -9 | comp MB/s | Pareto (size vs decomp) |
|---|---|---|---|---|---|---|---|---|
| 1 | `amd_pcm_mt:3` | results/ | 657.8 MB | 2.65x | 51 | 0.09x | 49 | yes |
| 2 | `amd_pcm_mt:2` | results/ | 659.0 MB | 2.64x | 55 | 0.09x | 62 | yes |
| 3 | `amd_planesbwt_mt:1` | results/ | 687.3 MB | 2.53x | 438 | 0.75x | 477 | yes |
| 4 | `planesxz:9` | results/ | 699.4 MB | 2.49x | 813 | 1.39x | 194 | yes |
| 5 | `planesxz:6` | results/ | 700.2 MB | 2.49x | 781 | 1.34x | 270 | |
| 6 | `pp:zstd19L` | xt round 1 | 732.5 MB | 2.38x | **3197** | **2.64x** | 73 | yes |
| 7 | `bkA:19lg` | xt2 round 2 | 732.9 MB | 2.38x | 2213 | 1.78x | 247 | |
| 8 | `bk16:19lg` | xt2 round 2 | 733.6 MB | 2.37x | 2059 | 1.65x | 231 | |
| 9 | `planes:19` | results/ | 734.6 MB | 2.37x | 967 | 1.66x | 300 | |
| 10 | `planes:9` | results/ | 774.5 MB | 2.25x | 936 | 1.61x | 1160 | |
| 11 | `pp:zstd9L` | xt round 1 | 777.3 MB | 2.24x | 1833 | 1.51x | 1143 | |
| 12 | `bk4:9g` | xt2 round 2 | 780.2 MB | 2.23x | 1633 | 1.31x | 994 | |
| 13 | `planes:3` | results/ | 790.9 MB | 2.20x | 1139 | 1.95x | 1512 | |
| 14 | `bk4:3g` | xt2 round 2 | 794.1 MB | 2.19x | 1648 | 1.32x | 1485 | |
| – | `raw:zstd9R` | xt round 1 | 1740.7 MB | 1.00x | 4776 | 3.94x | 500 | yes (fastest, no size gain) |
| – | plain zstd -9 | xt2 | 1740.7 MB | 1.00x | 1245 | 1.00x | 517 | |
