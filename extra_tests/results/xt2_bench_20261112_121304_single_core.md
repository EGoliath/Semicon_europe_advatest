# xt2 bench (single_core) - 3 files, 1 thread(s)

Reference `raw:z9` = plain zstd -9. Size change vs zstd -9: negative = smaller.

| config | compressed | ratio | vs zstd9 | size vs zstd9 | comp MB/s | decomp MB/s | verified |
|---|---|---|---|---|---|---|---|
| `bkA:19lg` | 14.2 MB | 73.0x | 3.67x | -72.7% | 99 | 468 | 3/3 |
| `bk4:9g` | 15.8 MB | 65.7x | 3.30x | -69.7% | 410 | 444 | 3/3 |
| `bk4:3g` | 16.5 MB | 62.9x | 3.16x | -68.3% | 519 | 444 | 3/3 |
| `raw:z19` | 31.6 MB | 32.9x | 1.65x | -39.5% | 6 | 1895 | 3/3 |
| `raw:z9` | 52.2 MB | 19.9x | 1.00x | +0.0% | 137 | 1615 | 3/3 |
