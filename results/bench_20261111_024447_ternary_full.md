# Pattern zstd benchmark (20261111_024447_ternary_full)

29 files, source: `extracted`, threads: -1

| config | files | original | compressed | ratio | vs .pat zip | comp MB/s | decomp MB/s | verified |
|---|---|---|---|---|---|---|---|---|
| raw:9 | 29 | 22.8 GB | 1.5 GB | 14.9x | 1.1x | 248 | 848 | 29/29 |
| auto:none | 29 | 22.8 GB | 2.8 GB | 8.1x | 0.6x | 1906 | 996 | 29/29 |
| auto:9 | 29 | 22.8 GB | 751.9 MB | 31.0x | 2.3x | 867 | 963 | 29/29 |
| t5:none | 29 | 22.8 GB | 5.1 GB | 4.4x | 0.3x | 581 | 1029 | 29/29 |
| t5:9 | 29 | 22.8 GB | 1.2 GB | 18.7x | 1.4x | 353 | 846 | 29/29 |
| t5row:none | 29 | 22.8 GB | 4.7 GB | 4.9x | 0.4x | 1970 | 1095 | 29/29 |
| t5row:9 | 29 | 22.8 GB | 1.2 GB | 19.2x | 1.4x | 467 | 910 | 29/29 |
| t5col:none | 29 | 22.8 GB | 4.5 GB | 5.1x | 0.4x | 1733 | 1039 | 29/29 |
| t5col:9 | 29 | 22.8 GB | 838.0 MB | 27.8x | 2.0x | 657 | 938 | 29/29 |
| mixed:none | 29 | 22.8 GB | 2.6 GB | 8.6x | 0.6x | 2000 | 1062 | 29/29 |
| mixed:9 | 29 | 22.8 GB | 752.5 MB | 31.0x | 2.3x | 931 | 988 | 29/29 |
