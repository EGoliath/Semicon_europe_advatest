# Pattern zstd benchmark (20261111_031452_best_hybrid)

29 files, source: `extracted`, threads: -1

| config | files | original | compressed | ratio | vs .pat zip | comp MB/s | decomp MB/s | verified |
|---|---|---|---|---|---|---|---|---|
| raw:9 | 29 | 22.8 GB | 1.5 GB | 14.9x | 1.1x | 227 | 746 | 29/29 |
| auto:3 | 29 | 22.8 GB | 758.6 MB | 30.7x | 2.3x | 1046 | 794 | 29/29 |
| auto:9 | 29 | 22.8 GB | 751.9 MB | 31.0x | 2.3x | 813 | 788 | 29/29 |
| auto:19 | 29 | 22.8 GB | 710.7 MB | 32.8x | 2.4x | 59 | 862 | 29/29 |
| mixed:3 | 29 | 22.8 GB | 758.7 MB | 30.7x | 2.3x | 1254 | 897 | 29/29 |
| mixed:9 | 29 | 22.8 GB | 752.5 MB | 31.0x | 2.3x | 879 | 873 | 29/29 |
| mixed:19 | 29 | 22.8 GB | 709.4 MB | 32.9x | 2.4x | 53 | 966 | 29/29 |
| best:3 | 29 | 22.8 GB | 758.3 MB | 30.7x | 2.3x | 650 | 744 | 29/29 |
| best:9 | 29 | 22.8 GB | 751.7 MB | 31.0x | 2.3x | 447 | 747 | 29/29 |
| best:19 | 29 | 22.8 GB | 709.0 MB | 32.9x | 2.4x | 28 | 892 | 29/29 |
