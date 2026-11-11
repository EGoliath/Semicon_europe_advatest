# Pattern zstd benchmark (20261111_082512_planes_full)

29 files, source: `extracted`, threads: -1

| config | files | original | compressed | ratio | vs .pat zip | comp MB/s | decomp MB/s | verified |
|---|---|---|---|---|---|---|---|---|
| raw:9 | 29 | 22.8 GB | 1.5 GB | 14.9x | 1.1x | 204 | 617 | 29/29 |
| mixed:9 | 29 | 22.8 GB | 752.5 MB | 31.0x | 2.3x | 901 | 717 | 29/29 |
| mixed:19 | 29 | 22.8 GB | 709.4 MB | 32.9x | 2.4x | 48 | 841 | 29/29 |
| planes:3 | 29 | 22.8 GB | 754.3 MB | 30.9x | 2.3x | 1496 | 996 | 29/29 |
| planes:9 | 29 | 22.8 GB | 738.6 MB | 31.6x | 2.3x | 1037 | 945 | 29/29 |
| planes:19 | 29 | 22.8 GB | 700.6 MB | 33.3x | 2.4x | 309 | 1030 | 29/29 |
| planesxz:6 | 29 | 22.8 GB | 667.8 MB | 34.9x | 2.6x | 257 | 808 | 29/29 |
| planesxz:9 | 29 | 22.8 GB | 667.0 MB | 34.9x | 2.6x | 179 | 797 | 29/29 |
