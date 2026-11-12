# Top 25 of all tests by size (full corpus: 29 files, 24.44 GB, all 20 threads, every row verified 29/29)

Size reference: plain zstd -9 = **1740.7 MB**. Size improvement = how much smaller than that (positive = better).
Speed improvement = vs zstd -9 measured by the *same* bench script (positive = faster), because the scripts time differently:
earlier `results/` zstd -9 (window 2^27, 1640.0 MB): comp 210 / decomp 583 MB/s; round 1: 505 / 1211 MB/s; round 2: 517 / 1245 MB/s.

| # | config | from | size | ratio | size improvement | comp time | comp MB/s | comp improvement | decomp time | decomp MB/s | decomp improvement |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `amd_pcm_mt:3` | earlier (results/) | 657.8 MB | 37.2x | +62.2% | 495 s | 49 | -77% | 482 s | 51 | -91% |
| 2 | `amd_pcm_mt:2` | earlier (results/) | 659.0 MB | 37.1x | +62.1% | 397 s | 62 | -70% | 444 s | 55 | -91% |
| 3 | `amd_planesbwt_mt:1` | earlier (results/) | 687.3 MB | 35.6x | +60.5% | 51 s | 477 | +127% | 56 s | 438 | -25% |
| 4 | `planesxz:9` | earlier (results/) | 699.4 MB | 34.9x | +59.8% | 126 s | 194 | -8% | 30 s | 813 | +39% |
| 5 | `amd_planesxz_mt:9` | earlier (results/) | 699.4 MB | 34.9x | +59.8% | 116 s | 211 | +0% | 31 s | 792 | +36% |
| 6 | `planesxz:6` | earlier (results/) | 700.2 MB | 34.9x | +59.8% | 91 s | 270 | +29% | 31 s | 781 | +34% |
| 7 | `amd_planesxz_mt:6` | earlier (results/) | 700.2 MB | 34.9x | +59.8% | 100 s | 244 | +16% | 31 s | 784 | +34% |
| 8 | `pp:zstd19L` | round 1 (xt) | 732.5 MB | 33.4x | +57.9% | 335 s | 73 | -86% | 8 s | 3197 | +164% |
| 9 | `bkA:19lg` | round 2 (xt2) | 732.9 MB | 33.3x | +57.9% | 99 s | 247 | -52% | 11 s | 2213 | +78% |
| 10 | `bk16:19lg` | round 2 (xt2) | 733.6 MB | 33.3x | +57.9% | 106 s | 231 | -55% | 12 s | 2059 | +65% |
| 11 | `planes:19` | earlier (results/) | 734.6 MB | 33.3x | +57.8% | 82 s | 300 | +43% | 25 s | 967 | +66% |
| 12 | `amd_planes_mt:19` | earlier (results/) | 734.6 MB | 33.3x | +57.8% | 80 s | 304 | +45% | 26 s | 931 | +60% |
| 13 | `best:19` | earlier (results/) | 743.4 MB | 32.9x | +57.3% | 1024 s | 24 | -89% | 34 s | 722 | +24% |
| 14 | `amd_best_mt:19` | earlier (results/) | 743.4 MB | 32.9x | +57.3% | 1027 s | 24 | -89% | 33 s | 739 | +27% |
| 15 | `mixed:19` | earlier (results/) | 743.8 MB | 32.9x | +57.3% | 536 s | 46 | -78% | 33 s | 750 | +29% |
| 16 | `amd_mixed_mt:19` | earlier (results/) | 743.8 MB | 32.9x | +57.3% | 534 s | 46 | -78% | 32 s | 767 | +32% |
| 17 | `auto:19` | earlier (results/) | 745.2 MB | 32.8x | +57.2% | 494 s | 49 | -77% | 38 s | 641 | +10% |
| 18 | `amd_auto_mt:19` | earlier (results/) | 745.2 MB | 32.8x | +57.2% | 493 s | 50 | -76% | 39 s | 623 | +7% |
| 19 | `planes:9` | earlier (results/) | 774.5 MB | 31.6x | +55.5% | 21 s | 1160 | +452% | 26 s | 936 | +61% |
| 20 | `amd_planes_mt:9` | earlier (results/) | 774.5 MB | 31.6x | +55.5% | 22 s | 1096 | +422% | 27 s | 913 | +57% |
| 21 | `pp:zstd9L` | round 1 (xt) | 777.3 MB | 31.4x | +55.3% | 21 s | 1143 | +126% | 13 s | 1833 | +51% |
| 22 | `bk4:9g` | round 2 (xt2) | 780.2 MB | 31.3x | +55.2% | 25 s | 994 | +92% | 15 s | 1633 | +31% |
| 23 | `best:9` | earlier (results/) | 788.2 MB | 31.0x | +54.7% | 46 s | 530 | +152% | 38 s | 651 | +12% |
| 24 | `auto:9` | earlier (results/) | 788.5 MB | 31.0x | +54.7% | 30 s | 813 | +287% | 31 s | 788 | +35% |
| 25 | `amd_best_mt:9` | earlier (results/) | 788.9 MB | 31.0x | +54.7% | 49 s | 502 | +139% | 38 s | 650 | +11% |
| base | `raw:9` (zstd -9, window 2^27) | earlier (results/) | 1640.0 MB | 14.9x | +5.8% | 117 s | 210 | +0% | 42 s | 583 | +0% |
| base | `raw:z9` (plain zstd -9) | round 2 (xt2) | 1740.7 MB | 14.0x | +0.0% | 47 s | 517 | +0% | 20 s | 1245 | +0% |
| base | `raw:zstd9` (plain zstd -9) | round 1 (xt) | 1740.7 MB | 14.0x | +0.0% | 48 s | 505 | +0% | 20 s | 1211 | +0% |
