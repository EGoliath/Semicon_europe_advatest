# Pattern zstd benchmark (20261112_042017_amd_subset_st)

13 files, source: `extracted`, threads: -1, CPU: 14 physical cores / 20 threads, 1 L3 domain(s), patamd ISA variant: avx2

| config | files | original | compressed | ratio | vs .pat zip | comp MB/s | decomp MB/s | verified |
|---|---|---|---|---|---|---|---|---|
| amd_planesxz_st:9 | 13 | 3.1 GB | 39.0 MB | 82.6x | 3.8x | 46 | 592 | 13/13 |
| amd_planesxz_st:6 | 13 | 3.1 GB | 39.1 MB | 82.3x | 3.8x | 80 | 572 | 13/13 |
| amd_planes_st:19 | 13 | 3.1 GB | 42.8 MB | 75.2x | 3.5x | 99 | 913 | 13/13 |
| amd_best_st:19 | 13 | 3.1 GB | 44.2 MB | 72.9x | 3.4x | 37 | 849 | 13/13 |
| amd_mixed_st:19 | 13 | 3.1 GB | 44.2 MB | 72.8x | 3.4x | 74 | 779 | 13/13 |
| amd_auto_st:19 | 13 | 3.1 GB | 44.3 MB | 72.6x | 3.4x | 74 | 904 | 13/13 |
| amd_planes_st:9 | 13 | 3.1 GB | 47.1 MB | 68.3x | 3.2x | 578 | 1039 | 13/13 |
| amd_best_st:9 | 13 | 3.1 GB | 49.2 MB | 65.5x | 3.0x | 272 | 915 | 13/13 |
| amd_pcm_st:2 | 13 | 3.1 GB | 33.2 MB | 97.0x | 4.5x | 30 | 30 | 13/13 |
| amd_pcm_st:3 | 13 | 3.1 GB | 33.1 MB | 97.3x | 4.5x | 26 | 27 | 13/13 |
| amd_planesbwt_st:1 | 13 | 3.1 GB | 37.7 MB | 85.5x | 4.0x | 229 | 247 | 13/13 |
