# Black-box benchmark: tries.exe vs gzip / zstd / xz on the hackathon sample corpus (001–029)

Date: 2026-11-10. Machine: Windows 11, 8 cores, 8 GB RAM, every codec single-threaded.

## Setup

- **Under test:** `tries.exe` (`tests/ClaudeTries/tries.c`) after the integrity fix of 2026-11-10: zstd content checksum on, truncated frames rejected, empty `.compr` rejected, output deleted on any failure. `pack1` and `pack9` are `tries c pack 1|9`.
- **Baselines:** `zstd3`, `zstd9` and `zstd19` use Python's stdlib `compression.zstd` (libzstd 1.5.7, single thread, streaming). This is independent of the zstd code inside tries.exe. `gzip6` is GNU gzip 1.14 at `-6`. `xz6` is XZ Utils 5.8.3 at `-6 -T1`. `zstd19` and `xz6` ran only on files under 100 MB, because they run at about 1 MB/s.
- **Input:** `Vectors.vec` from each `.pat` archive, unzipped (zip CRC checked), one archive at a time. Each archive was deleted after its run.
- **Per run:**
  1. Compress in a fresh folder, with TEMP pointed at an empty folder.
  2. Move **only** the compressed file to a second fresh folder, and rename the original away.
  3. Decompress in a new process.
  4. Compare SHA-256 with the original.
  5. Record the results, then delete the decompressed and compressed files.
- **Peak disk usage** stayed under 20 GB. The largest working set was about 5.5 GB, for 028.
- **Times** are wall clock around each process, including disk reads and writes. MB/s means 10^6 bytes of `.vec` per second. Memory is peak private commit; the memory-mapped input is not counted.
- Python start-up adds about 30 ms to each zstd run. That only matters for files under about 10 MB.

## Integrity

- 161 round trips, **161 byte-exact**, 0 failed.
- No side files were created in the work folder, the TEMP folder or next to the exe.

## Totals over all files

Only methods run on every file are included: pack1, pack9, zstd3, zstd9, gzip6.

| method | original | compressed | ratio | size vs zstd9 | compress time | decompress time | compress MB/s | decompress MB/s | peak MB c / d |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| pack1 | 24.44 GB | 814.9 MB | 29.99x | 2.14x smaller | 135 s | 83 s | 180.5 | 295.0 | 10 / 11 |
| pack9 | 24.44 GB | 808.7 MB | 30.22x | 2.15x smaller | 204 s | 78 s | 119.9 | 311.4 | 23 / 14 |
| zstd3 | 24.44 GB | 2.22 GB | 11.03x | 1.27x larger | 129 s | 115 s | 189.1 | 213.1 | 14 / 16 |
| zstd9 | 24.44 GB | 1.74 GB | 14.04x | baseline | 751 s | 101 s | 32.5 | 242.1 | 25 / 18 |
| gzip6 | 24.44 GB | 1.80 GB | 13.57x | 1.04x larger | 1568 s | 130 s | 15.6 | 188.0 | 6 / 6 |

**Headline:** pack9 output is 2.15x smaller than zstd9. It compresses 3.7x faster (204 s against 751 s) and decompresses 1.29x faster (78 s against 101 s). pack1 matches zstd3's compression speed and its output is 2.72x smaller.

## Per file: pack9 vs zstd9 (head to head)

| file | size | pack9 size | zstd9 size | pack9 ratio | zstd9 ratio | pack9 smaller by | compress s pack9 / zstd9 | decompress s pack9 / zstd9 | compress MB/s pack9 / zstd9 | decompress MB/s pack9 / zstd9 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 001 | 20.1 KB | 309 B | 769 B | 64.96x | 26.10x | 2.49x | 0.04 / 0.14 | 0.02 / 0.12 | 0.5 / 0.1 | 1.2 / 0.2 |
| 002 | 4.1 MB | 4.0 KB | 20.9 KB | 1023.41x | 196.42x | 5.21x | 0.06 / 0.21 | 0.03 / 0.17 | 74.1 / 20.0 | 152.7 / 23.7 |
| 003 | 2.50 GB | 130.1 MB | 296.1 MB | 19.20x | 8.44x | 2.27x | 16.51 / 119.22 | 7.34 / 15.49 | 151.3 / 21.0 | 340.5 / 161.3 |
| 004 | 1.44 GB | 70.3 MB | 160.4 MB | 20.50x | 8.99x | 2.28x | 9.07 / 59.79 | 3.70 / 5.63 | 159.0 / 24.1 | 389.2 / 256.0 |
| 005 | 1.43 GB | 64.4 MB | 153.6 MB | 22.27x | 9.34x | 2.38x | 9.14 / 57.13 | 5.96 / 7.38 | 156.9 / 25.1 | 240.8 / 194.4 |
| 006 | 187.7 MB | 7.5 MB | 16.6 MB | 25.10x | 11.33x | 2.22x | 1.39 / 6.69 | 0.45 / 0.75 | 134.9 / 28.1 | 415.5 / 250.3 |
| 007 | 703.2 MB | 13.6 MB | 36.2 MB | 51.67x | 19.43x | 2.66x | 5.70 / 16.31 | 2.04 / 2.85 | 123.4 / 43.1 | 345.6 / 247.1 |
| 008 | 1.68 GB | 138.7 MB | 230.9 MB | 12.11x | 7.27x | 1.67x | 20.69 / 91.53 | 5.81 / 7.87 | 81.2 / 18.4 | 289.0 / 213.5 |
| 009 | 1.79 GB | 24.8 MB | 61.5 MB | 72.12x | 29.07x | 2.48x | 15.07 / 30.80 | 6.10 / 5.25 | 118.7 / 58.1 | 293.2 / 340.5 |
| 010 | 1.05 GB | 18.2 MB | 48.2 MB | 58.02x | 21.83x | 2.66x | 8.26 / 24.32 | 2.93 / 3.47 | 127.5 / 43.3 | 360.0 / 303.5 |
| 011 | 522.7 MB | 6.2 MB | 17.9 MB | 84.77x | 29.23x | 2.90x | 3.81 / 9.16 | 1.40 / 2.13 | 137.1 / 57.1 | 374.7 / 245.8 |
| 012 | 41.7 MB | 726.2 KB | 2.1 MB | 57.46x | 19.72x | 2.91x | 0.37 / 1.07 | 0.13 / 0.29 | 113.3 / 38.8 | 313.1 / 142.5 |
| 013 | 4.6 MB | 5.4 KB | 31.7 KB | 851.16x | 143.95x | 5.91x | 0.06 / 0.15 | 0.05 / 0.14 | 78.2 / 30.8 | 98.5 / 32.6 |
| 014 | 334.9 MB | 4.4 MB | 16.0 MB | 76.77x | 20.99x | 3.66x | 2.52 / 7.78 | 0.99 / 1.05 | 133.0 / 43.1 | 338.5 / 318.7 |
| 015 | 13.4 KB | 310 B | 639 B | 43.28x | 21.00x | 2.06x | 0.04 / 0.12 | 0.01 / 0.12 | 0.4 / 0.1 | 0.9 / 0.1 |
| 016 | 1.6 MB | 31.6 KB | 52.6 KB | 51.09x | 30.71x | 1.66x | 0.05 / 0.14 | 0.02 / 0.14 | 32.6 / 11.1 | 74.0 / 11.5 |
| 017 | 4.1 MB | 4.0 KB | 20.9 KB | 1023.41x | 196.42x | 5.21x | 0.04 / 0.15 | 0.02 / 0.15 | 100.3 / 27.9 | 168.7 / 27.4 |
| 018 | 1.24 GB | 27.4 MB | 56.4 MB | 45.14x | 21.90x | 2.06x | 10.44 / 28.31 | 3.30 / 3.96 | 118.4 / 43.6 | 374.0 / 312.4 |
| 019 | 359.2 MB | 28.3 MB | 45.8 MB | 12.70x | 7.84x | 1.62x | 3.94 / 18.64 | 1.09 / 1.50 | 91.2 / 19.3 | 328.0 / 239.3 |
| 020 | 1.85 GB | 84.5 MB | 189.4 MB | 21.93x | 9.78x | 2.24x | 13.59 / 80.06 | 6.67 / 7.90 | 136.3 / 23.1 | 277.7 / 234.4 |
| 021 | 67.7 MB | 914.6 KB | 2.5 MB | 74.01x | 27.62x | 2.68x | 0.53 / 1.31 | 0.18 / 0.30 | 127.3 / 51.8 | 379.1 / 223.3 |
| 022 | 223.9 MB | 16.2 MB | 26.6 MB | 13.84x | 8.42x | 1.64x | 2.45 / 10.52 | 0.63 / 1.05 | 91.2 / 21.3 | 354.8 / 213.4 |
| 023 | 1.09 GB | 38.4 MB | 75.5 MB | 28.42x | 14.47x | 1.96x | 12.20 / 34.50 | 3.30 / 4.05 | 89.5 / 31.7 | 330.5 / 269.4 |
| 024 | 1.20 GB | 25.2 MB | 60.5 MB | 47.39x | 19.76x | 2.40x | 11.54 / 27.70 | 4.36 / 4.09 | 103.6 / 43.2 | 274.3 / 292.1 |
| 025 | 1.79 GB | 25.9 MB | 62.9 MB | 69.01x | 28.44x | 2.43x | 15.23 / 32.92 | 6.16 / 6.85 | 117.4 / 54.3 | 290.3 / 261.0 |
| 026 | 1.79 GB | 25.7 MB | 62.7 MB | 69.47x | 28.53x | 2.43x | 15.26 / 33.14 | 7.30 / 8.33 | 117.2 / 54.0 | 244.9 / 214.7 |
| 027 | 237.9 MB | 4.5 MB | 12.1 MB | 52.60x | 19.70x | 2.67x | 1.99 / 5.79 | 0.70 / 0.84 | 119.7 / 41.1 | 338.2 / 282.2 |
| 028 | 2.52 GB | 48.7 MB | 91.8 MB | 51.80x | 27.48x | 1.89x | 21.13 / 45.94 | 6.75 / 7.91 | 119.4 / 54.9 | 373.7 / 318.9 |
| 029 | 375.7 MB | 4.0 MB | 14.9 MB | 94.38x | 25.21x | 3.74x | 2.77 / 7.78 | 1.02 / 1.18 | 135.4 / 48.3 | 367.0 / 318.8 |

- Weakest pack9 gains over zstd9: 019 1.62x, 022 1.64x, 016 1.66x, 008 1.67x, 028 1.89x.
- Strongest: 013 5.91x, 017 5.21x, 002 5.21x.
- Files where pack9 output is larger than zstd9: none.
- Files where any baseline beats pack9: none.

## All methods, per file


### Compressed size

| file | size | pack1 | pack9 | zstd3 | zstd9 | zstd19 | gzip6 | xz6 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 001 | 20.1 KB | 413 B | 309 B | 988 B | 769 B | 546 B | 767 B | 656 B |
| 002 | 4.1 MB | 5.9 KB | 4.0 KB | 53.5 KB | 20.9 KB | 8.0 KB | 27.2 KB | 14.0 KB |
| 003 | 2.50 GB | 129.7 MB | 130.1 MB | 356.9 MB | 296.1 MB | – | 293.5 MB | – |
| 004 | 1.44 GB | 71.2 MB | 70.3 MB | 192.2 MB | 160.4 MB | – | 173.0 MB | – |
| 005 | 1.43 GB | 65.6 MB | 64.4 MB | 183.8 MB | 153.6 MB | – | 166.0 MB | – |
| 006 | 187.7 MB | 7.2 MB | 7.5 MB | 20.6 MB | 16.6 MB | – | 18.1 MB | – |
| 007 | 703.2 MB | 14.1 MB | 13.6 MB | 50.6 MB | 36.2 MB | – | 37.4 MB | – |
| 008 | 1.68 GB | 134.3 MB | 138.7 MB | 278.0 MB | 230.9 MB | – | 224.7 MB | – |
| 009 | 1.79 GB | 26.2 MB | 24.8 MB | 95.9 MB | 61.5 MB | – | 66.2 MB | – |
| 010 | 1.05 GB | 19.2 MB | 18.2 MB | 71.9 MB | 48.2 MB | – | 49.2 MB | – |
| 011 | 522.7 MB | 6.6 MB | 6.2 MB | 26.8 MB | 17.9 MB | – | 19.6 MB | – |
| 012 | 41.7 MB | 770.6 KB | 726.2 KB | 2.9 MB | 2.1 MB | 1.2 MB | 2.2 MB | 1.0 MB |
| 013 | 4.6 MB | 7.8 KB | 5.4 KB | 67.3 KB | 31.7 KB | 8.9 KB | 35.8 KB | 17.7 KB |
| 014 | 334.9 MB | 6.2 MB | 4.4 MB | 22.3 MB | 16.0 MB | – | 17.1 MB | – |
| 015 | 13.4 KB | 413 B | 310 B | 851 B | 639 B | 512 B | 722 B | 648 B |
| 016 | 1.6 MB | 32.6 KB | 31.6 KB | 62.9 KB | 52.6 KB | 39.8 KB | 75.1 KB | 37.6 KB |
| 017 | 4.1 MB | 5.9 KB | 4.0 KB | 53.5 KB | 20.9 KB | 8.0 KB | 27.2 KB | 14.0 KB |
| 018 | 1.24 GB | 28.6 MB | 27.4 MB | 68.8 MB | 56.4 MB | – | 61.6 MB | – |
| 019 | 359.2 MB | 27.7 MB | 28.3 MB | 54.5 MB | 45.8 MB | – | 45.0 MB | – |
| 020 | 1.85 GB | 81.4 MB | 84.5 MB | 227.7 MB | 189.4 MB | – | 187.5 MB | – |
| 021 | 67.7 MB | 932.4 KB | 914.6 KB | 3.7 MB | 2.5 MB | 1.6 MB | 2.7 MB | 1.3 MB |
| 022 | 223.9 MB | 15.5 MB | 16.2 MB | 32.0 MB | 26.6 MB | – | 26.1 MB | – |
| 023 | 1.09 GB | 39.1 MB | 38.4 MB | 89.5 MB | 75.5 MB | – | 77.5 MB | – |
| 024 | 1.20 GB | 27.2 MB | 25.2 MB | 87.6 MB | 60.5 MB | – | 63.0 MB | – |
| 025 | 1.79 GB | 27.2 MB | 25.9 MB | 98.6 MB | 62.9 MB | – | 68.3 MB | – |
| 026 | 1.79 GB | 27.0 MB | 25.7 MB | 98.1 MB | 62.7 MB | – | 68.0 MB | – |
| 027 | 237.9 MB | 4.7 MB | 4.5 MB | 16.9 MB | 12.1 MB | – | 12.5 MB | – |
| 028 | 2.52 GB | 49.7 MB | 48.7 MB | 115.0 MB | 91.8 MB | – | 106.3 MB | – |
| 029 | 375.7 MB | 4.8 MB | 4.0 MB | 22.2 MB | 14.9 MB | – | 15.7 MB | – |

### Compression ratio (original / compressed)

| file | size | pack1 | pack9 | zstd3 | zstd9 | zstd19 | gzip6 | xz6 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 001 | 20.1 KB | 48.60x | 64.96x | 20.32x | 26.10x | 36.76x | 26.17x | 30.60x |
| 002 | 4.1 MB | 699.87x | 1023.41x | 76.88x | 196.42x | 511.96x | 150.95x | 294.49x |
| 003 | 2.50 GB | 19.27x | 19.20x | 7.00x | 8.44x | – | 8.52x | – |
| 004 | 1.44 GB | 20.24x | 20.50x | 7.50x | 8.99x | – | 8.33x | – |
| 005 | 1.43 GB | 21.86x | 22.27x | 7.80x | 9.34x | – | 8.64x | – |
| 006 | 187.7 MB | 26.04x | 25.10x | 9.10x | 11.33x | – | 10.36x | – |
| 007 | 703.2 MB | 49.82x | 51.67x | 13.90x | 19.43x | – | 18.78x | – |
| 008 | 1.68 GB | 12.51x | 12.11x | 6.04x | 7.27x | – | 7.47x | – |
| 009 | 1.79 GB | 68.34x | 72.12x | 18.64x | 29.07x | – | 27.02x | – |
| 010 | 1.05 GB | 54.83x | 58.02x | 14.65x | 21.83x | – | 21.40x | – |
| 011 | 522.7 MB | 79.34x | 84.77x | 19.51x | 29.23x | – | 26.64x | – |
| 012 | 41.7 MB | 54.15x | 57.46x | 14.19x | 19.72x | 34.08x | 18.95x | 40.33x |
| 013 | 4.6 MB | 588.68x | 851.16x | 67.85x | 143.95x | 513.10x | 127.69x | 258.67x |
| 014 | 334.9 MB | 54.12x | 76.77x | 15.04x | 20.99x | – | 19.62x | – |
| 015 | 13.4 KB | 32.48x | 43.28x | 15.77x | 21.00x | 26.20x | 18.58x | 20.70x |
| 016 | 1.6 MB | 49.57x | 51.09x | 25.67x | 30.71x | 40.63x | 21.51x | 43.03x |
| 017 | 4.1 MB | 699.87x | 1023.41x | 76.88x | 196.42x | 511.96x | 150.95x | 294.49x |
| 018 | 1.24 GB | 43.24x | 45.14x | 17.96x | 21.90x | – | 20.06x | – |
| 019 | 359.2 MB | 12.99x | 12.70x | 6.59x | 7.84x | – | 7.98x | – |
| 020 | 1.85 GB | 22.75x | 21.93x | 8.13x | 9.78x | – | 9.88x | – |
| 021 | 67.7 MB | 72.59x | 74.01x | 18.49x | 27.62x | 41.19x | 25.18x | 52.13x |
| 022 | 223.9 MB | 14.41x | 13.84x | 7.00x | 8.42x | – | 8.57x | – |
| 023 | 1.09 GB | 27.92x | 28.42x | 12.21x | 14.47x | – | 14.09x | – |
| 024 | 1.20 GB | 44.03x | 47.39x | 13.65x | 19.76x | – | 18.98x | – |
| 025 | 1.79 GB | 65.84x | 69.01x | 18.14x | 28.44x | – | 26.21x | – |
| 026 | 1.79 GB | 66.19x | 69.47x | 18.23x | 28.53x | – | 26.29x | – |
| 027 | 237.9 MB | 50.11x | 52.60x | 14.07x | 19.70x | – | 19.02x | – |
| 028 | 2.52 GB | 50.80x | 51.80x | 21.94x | 27.48x | – | 23.74x | – |
| 029 | 375.7 MB | 78.19x | 94.38x | 16.93x | 25.21x | – | 23.88x | – |

### Compress time (s)

| file | size | pack1 | pack9 | zstd3 | zstd9 | zstd19 | gzip6 | xz6 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 001 | 20.1 KB | 0.04 | 0.04 | 0.13 | 0.14 | 0.19 | 0.05 | 0.04 |
| 002 | 4.1 MB | 0.05 | 0.06 | 0.14 | 0.21 | 0.22 | 0.06 | 0.29 |
| 003 | 2.50 GB | 10.59 | 16.51 | 17.08 | 119.22 | – | 315.52 | – |
| 004 | 1.44 GB | 7.09 | 9.07 | 9.84 | 59.79 | – | 144.21 | – |
| 005 | 1.43 GB | 6.55 | 9.14 | 9.47 | 57.13 | – | 140.68 | – |
| 006 | 187.7 MB | 0.87 | 1.39 | 1.32 | 6.69 | – | 13.67 | – |
| 007 | 703.2 MB | 4.10 | 5.70 | 3.11 | 16.31 | – | 32.49 | – |
| 008 | 1.68 GB | 10.83 | 20.69 | 12.71 | 91.53 | – | 213.87 | – |
| 009 | 1.79 GB | 11.78 | 15.07 | 6.61 | 30.80 | – | 51.53 | – |
| 010 | 1.05 GB | 6.30 | 8.26 | 4.69 | 24.32 | – | 42.66 | – |
| 011 | 522.7 MB | 3.06 | 3.81 | 1.94 | 9.16 | – | 16.61 | – |
| 012 | 41.7 MB | 0.27 | 0.37 | 0.30 | 1.07 | 25.76 | 2.10 | 27.51 |
| 013 | 4.6 MB | 0.05 | 0.06 | 0.14 | 0.15 | 0.21 | 0.05 | 0.32 |
| 014 | 334.9 MB | 1.99 | 2.52 | 1.58 | 7.78 | – | 13.16 | – |
| 015 | 13.4 KB | 0.04 | 0.04 | 0.12 | 0.12 | 0.17 | 0.04 | 0.03 |
| 016 | 1.6 MB | 0.04 | 0.05 | 0.13 | 0.14 | 0.58 | 0.12 | 0.77 |
| 017 | 4.1 MB | 0.04 | 0.04 | 0.13 | 0.15 | 0.20 | 0.05 | 0.26 |
| 018 | 1.24 GB | 5.92 | 10.44 | 5.30 | 28.31 | – | 37.89 | – |
| 019 | 359.2 MB | 2.20 | 3.94 | 2.66 | 18.64 | – | 47.14 | – |
| 020 | 1.85 GB | 8.25 | 13.59 | 13.00 | 80.06 | – | 147.88 | – |
| 021 | 67.7 MB | 0.46 | 0.53 | 0.38 | 1.31 | 32.69 | 2.61 | 32.97 |
| 022 | 223.9 MB | 1.40 | 2.45 | 1.57 | 10.52 | – | 24.65 | – |
| 023 | 1.09 GB | 7.39 | 12.20 | 6.13 | 34.50 | – | 50.83 | – |
| 024 | 1.20 GB | 7.58 | 11.54 | 5.47 | 27.70 | – | 53.03 | – |
| 025 | 1.79 GB | 11.04 | 15.23 | 6.79 | 32.92 | – | 57.75 | – |
| 026 | 1.79 GB | 10.77 | 15.26 | 6.59 | 33.14 | – | 54.84 | – |
| 027 | 237.9 MB | 1.50 | 1.99 | 1.19 | 5.79 | – | 11.54 | – |
| 028 | 2.52 GB | 12.92 | 21.13 | 9.10 | 45.94 | – | 79.27 | – |
| 029 | 375.7 MB | 2.24 | 2.77 | 1.65 | 7.78 | – | 13.34 | – |

### Decompress time (s)

| file | size | pack1 | pack9 | zstd3 | zstd9 | zstd19 | gzip6 | xz6 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 001 | 20.1 KB | 0.02 | 0.02 | 0.14 | 0.12 | 0.14 | 0.07 | 0.03 |
| 002 | 4.1 MB | 0.03 | 0.03 | 0.20 | 0.17 | 0.16 | 0.06 | 0.05 |
| 003 | 2.50 GB | 7.21 | 7.34 | 14.33 | 15.49 | – | 22.45 | – |
| 004 | 1.44 GB | 3.54 | 3.70 | 7.06 | 5.63 | – | 9.74 | – |
| 005 | 1.43 GB | 6.18 | 5.96 | 7.00 | 7.38 | – | 8.97 | – |
| 006 | 187.7 MB | 0.44 | 0.45 | 1.01 | 0.75 | – | 0.89 | – |
| 007 | 703.2 MB | 2.07 | 2.04 | 2.71 | 2.85 | – | 2.65 | – |
| 008 | 1.68 GB | 5.80 | 5.81 | 9.27 | 7.87 | – | 12.48 | – |
| 009 | 1.79 GB | 5.58 | 6.10 | 6.52 | 5.25 | – | 7.32 | – |
| 010 | 1.05 GB | 2.94 | 2.93 | 4.32 | 3.47 | – | 4.16 | – |
| 011 | 522.7 MB | 1.39 | 1.40 | 1.89 | 2.13 | – | 1.87 | – |
| 012 | 41.7 MB | 0.15 | 0.13 | 0.27 | 0.29 | 0.23 | 0.22 | 0.26 |
| 013 | 4.6 MB | 0.03 | 0.05 | 0.15 | 0.14 | 0.14 | 0.05 | 0.07 |
| 014 | 334.9 MB | 0.93 | 0.99 | 1.38 | 1.05 | – | 1.14 | – |
| 015 | 13.4 KB | 0.02 | 0.01 | 0.14 | 0.12 | 0.12 | 0.04 | 0.07 |
| 016 | 1.6 MB | 0.04 | 0.02 | 0.14 | 0.14 | 0.13 | 0.05 | 0.04 |
| 017 | 4.1 MB | 0.03 | 0.02 | 0.17 | 0.15 | 0.12 | 0.05 | 0.04 |
| 018 | 1.24 GB | 4.31 | 3.30 | 4.74 | 3.96 | – | 4.38 | – |
| 019 | 359.2 MB | 0.99 | 1.09 | 1.89 | 1.50 | – | 2.33 | – |
| 020 | 1.85 GB | 5.89 | 6.67 | 9.85 | 7.90 | – | 11.28 | – |
| 021 | 67.7 MB | 0.20 | 0.18 | 0.36 | 0.30 | 0.30 | 0.28 | 0.38 |
| 022 | 223.9 MB | 0.60 | 0.63 | 1.26 | 1.05 | – | 1.36 | – |
| 023 | 1.09 GB | 6.06 | 3.30 | 5.32 | 4.05 | – | 4.74 | – |
| 024 | 1.20 GB | 3.66 | 4.36 | 4.82 | 4.09 | – | 5.14 | – |
| 025 | 1.79 GB | 5.02 | 6.16 | 9.51 | 6.85 | – | 7.99 | – |
| 026 | 1.79 GB | 7.42 | 7.30 | 8.69 | 8.33 | – | 7.44 | – |
| 027 | 237.9 MB | 0.68 | 0.70 | 1.05 | 0.84 | – | 0.89 | – |
| 028 | 2.52 GB | 10.66 | 6.75 | 9.08 | 7.91 | – | 10.70 | – |
| 029 | 375.7 MB | 0.96 | 1.02 | 1.43 | 1.18 | – | 1.31 | – |

### Compress speed (MB/s of .vec)

Files under about 10 MB are dominated by process start-up, so their speeds are not meaningful.

| file | size | pack1 | pack9 | zstd3 | zstd9 | zstd19 | gzip6 | xz6 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 001 | 20.1 KB | 0.5 | 0.5 | 0.1 | 0.1 | 0.1 | 0.4 | 0.5 |
| 002 | 4.1 MB | 75.9 | 74.1 | 29.3 | 20.0 | 18.6 | 74.5 | 14.3 |
| 003 | 2.50 GB | 235.9 | 151.3 | 146.3 | 21.0 | – | 7.9 | – |
| 004 | 1.44 GB | 203.3 | 159.0 | 146.5 | 24.1 | – | 10.0 | – |
| 005 | 1.43 GB | 219.1 | 156.9 | 151.5 | 25.1 | – | 10.2 | – |
| 006 | 187.7 MB | 214.9 | 134.9 | 142.6 | 28.1 | – | 13.7 | – |
| 007 | 703.2 MB | 171.5 | 123.4 | 226.4 | 43.1 | – | 21.6 | – |
| 008 | 1.68 GB | 155.1 | 81.2 | 132.1 | 18.4 | – | 7.9 | – |
| 009 | 1.79 GB | 151.8 | 118.7 | 270.5 | 58.1 | – | 34.7 | – |
| 010 | 1.05 GB | 167.1 | 127.5 | 224.6 | 43.3 | – | 24.7 | – |
| 011 | 522.7 MB | 171.0 | 137.1 | 269.8 | 57.1 | – | 31.5 | – |
| 012 | 41.7 MB | 156.2 | 113.3 | 138.6 | 38.8 | 1.6 | 19.8 | 1.5 |
| 013 | 4.6 MB | 86.0 | 78.2 | 32.5 | 30.8 | 22.2 | 86.9 | 14.1 |
| 014 | 334.9 MB | 168.4 | 133.0 | 211.6 | 43.1 | – | 25.5 | – |
| 015 | 13.4 KB | 0.4 | 0.4 | 0.1 | 0.1 | 0.1 | 0.4 | 0.5 |
| 016 | 1.6 MB | 38.3 | 32.6 | 12.3 | 11.1 | 2.8 | 14.0 | 2.1 |
| 017 | 4.1 MB | 100.3 | 100.3 | 31.3 | 27.9 | 20.3 | 78.9 | 15.7 |
| 018 | 1.24 GB | 208.6 | 118.4 | 233.2 | 43.6 | – | 32.6 | – |
| 019 | 359.2 MB | 163.2 | 91.2 | 135.0 | 19.3 | – | 7.6 | – |
| 020 | 1.85 GB | 224.4 | 136.3 | 142.5 | 23.1 | – | 12.5 | – |
| 021 | 67.7 MB | 147.3 | 127.3 | 178.6 | 51.8 | 2.1 | 26.0 | 2.1 |
| 022 | 223.9 MB | 159.8 | 91.2 | 142.2 | 21.3 | – | 9.1 | – |
| 023 | 1.09 GB | 147.8 | 89.5 | 178.0 | 31.7 | – | 21.5 | – |
| 024 | 1.20 GB | 157.7 | 103.6 | 218.6 | 43.2 | – | 22.5 | – |
| 025 | 1.79 GB | 162.0 | 117.4 | 263.5 | 54.3 | – | 31.0 | – |
| 026 | 1.79 GB | 166.1 | 117.2 | 271.6 | 54.0 | – | 32.6 | – |
| 027 | 237.9 MB | 158.3 | 119.7 | 200.0 | 41.1 | – | 20.6 | – |
| 028 | 2.52 GB | 195.2 | 119.4 | 277.2 | 54.9 | – | 31.8 | – |
| 029 | 375.7 MB | 167.5 | 135.4 | 227.3 | 48.3 | – | 28.2 | – |

### Decompress speed (MB/s of .vec, written to disk)

| file | size | pack1 | pack9 | zstd3 | zstd9 | zstd19 | gzip6 | xz6 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 001 | 20.1 KB | 1.0 | 1.2 | 0.1 | 0.2 | 0.1 | 0.3 | 0.6 |
| 002 | 4.1 MB | 142.6 | 152.7 | 20.7 | 23.7 | 26.4 | 71.1 | 79.4 |
| 003 | 2.50 GB | 346.5 | 340.5 | 174.4 | 161.3 | – | 111.3 | – |
| 004 | 1.44 GB | 406.7 | 389.2 | 204.2 | 256.0 | – | 148.0 | – |
| 005 | 1.43 GB | 231.9 | 240.8 | 204.9 | 194.4 | – | 159.9 | – |
| 006 | 187.7 MB | 426.5 | 415.5 | 185.4 | 250.3 | – | 211.1 | – |
| 007 | 703.2 MB | 339.8 | 345.6 | 259.8 | 247.1 | – | 265.4 | – |
| 008 | 1.68 GB | 289.6 | 289.0 | 181.2 | 213.5 | – | 134.6 | – |
| 009 | 1.79 GB | 320.4 | 293.2 | 274.3 | 340.5 | – | 244.4 | – |
| 010 | 1.05 GB | 358.6 | 360.0 | 243.6 | 303.5 | – | 253.0 | – |
| 011 | 522.7 MB | 377.0 | 374.7 | 276.7 | 245.8 | – | 279.6 | – |
| 012 | 41.7 MB | 285.9 | 313.1 | 154.2 | 142.5 | 183.1 | 192.1 | 160.7 |
| 013 | 4.6 MB | 154.3 | 98.5 | 30.0 | 32.6 | 33.0 | 88.0 | 64.0 |
| 014 | 334.9 MB | 361.5 | 338.5 | 242.1 | 318.7 | – | 293.9 | – |
| 015 | 13.4 KB | 0.7 | 0.9 | 0.1 | 0.1 | 0.1 | 0.3 | 0.2 |
| 016 | 1.6 MB | 38.0 | 74.0 | 11.7 | 11.5 | 12.4 | 33.6 | 42.7 |
| 017 | 4.1 MB | 145.6 | 168.7 | 23.7 | 27.4 | 33.5 | 79.3 | 104.1 |
| 018 | 1.24 GB | 286.4 | 374.0 | 260.5 | 312.4 | – | 282.2 | – |
| 019 | 359.2 MB | 361.0 | 328.0 | 189.9 | 239.3 | – | 154.2 | – |
| 020 | 1.85 GB | 314.7 | 277.7 | 188.1 | 234.4 | – | 164.3 | – |
| 021 | 67.7 MB | 344.9 | 379.1 | 189.4 | 223.3 | 224.3 | 240.8 | 180.6 |
| 022 | 223.9 MB | 372.8 | 354.8 | 177.6 | 213.4 | – | 164.9 | – |
| 023 | 1.09 GB | 180.2 | 330.5 | 205.3 | 269.4 | – | 230.5 | – |
| 024 | 1.20 GB | 326.9 | 274.3 | 248.2 | 292.1 | – | 232.8 | – |
| 025 | 1.79 GB | 356.5 | 290.3 | 188.1 | 261.0 | – | 223.8 | – |
| 026 | 1.79 GB | 241.1 | 244.9 | 205.9 | 214.7 | – | 240.4 | – |
| 027 | 237.9 MB | 351.1 | 338.2 | 225.7 | 282.2 | – | 268.3 | – |
| 028 | 2.52 GB | 236.6 | 373.7 | 277.8 | 318.9 | – | 235.8 | – |
| 029 | 375.7 MB | 391.5 | 367.0 | 262.2 | 318.8 | – | 287.7 | – |

### Peak memory, compress / decompress (MB, private commit)

| file | size | pack1 | pack9 | zstd3 | zstd9 | zstd19 | gzip6 | xz6 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 001 | 20.1 KB | 3 / 4 | 17 / 6 | 12 / 11 | 24 / 14 | 98 / 17 | 6 / 6 | 94 / 9 |
| 002 | 4.1 MB | 3 / 10 | 17 / 13 | 14 / 15 | 25 / 16 | 100 / 20 | 6 / 6 | 94 / 9 |
| 003 | 2.50 GB | 10 / 11 | 23 / 14 | 13 / 16 | 25 / 18 | – | 6 / 6 | – |
| 004 | 1.44 GB | 7 / 11 | 20 / 14 | 13 / 16 | 25 / 18 | – | 6 / 6 | – |
| 005 | 1.43 GB | 7 / 11 | 20 / 14 | 13 / 16 | 25 / 18 | – | 6 / 6 | – |
| 006 | 187.7 MB | 4 / 11 | 18 / 14 | 13 / 15 | 24 / 17 | – | 6 / 6 | – |
| 007 | 703.2 MB | 6 / 11 | 20 / 14 | 13 / 16 | 25 / 17 | – | 6 / 6 | – |
| 008 | 1.68 GB | 8 / 11 | 22 / 14 | 14 / 16 | 25 / 18 | – | 6 / 6 | – |
| 009 | 1.79 GB | 8 / 11 | 22 / 14 | 14 / 16 | 25 / 18 | – | 6 / 6 | – |
| 010 | 1.05 GB | 7 / 11 | 21 / 14 | 13 / 16 | 25 / 17 | – | 6 / 6 | – |
| 011 | 522.7 MB | 6 / 11 | 20 / 14 | 13 / 16 | 25 / 18 | – | 6 / 6 | – |
| 012 | 41.7 MB | 5 / 11 | 19 / 14 | 14 / 15 | 25 / 17 | 100 / 21 | 6 / 6 | 94 / 9 |
| 013 | 4.6 MB | 4 / 11 | 17 / 14 | 14 / 15 | 25 / 17 | 100 / 21 | 6 / 6 | 94 / 9 |
| 014 | 334.9 MB | 6 / 11 | 19 / 14 | 14 / 15 | 25 / 18 | – | 6 / 6 | – |
| 015 | 13.4 KB | 3 / 4 | 17 / 6 | 12 / 12 | 24 / 13 | 99 / 18 | 6 / 6 | 94 / 9 |
| 016 | 1.6 MB | 4 / 6 | 17 / 9 | 13 / 15 | 25 / 17 | 100 / 21 | 6 / 6 | 94 / 9 |
| 017 | 4.1 MB | 3 / 10 | 17 / 13 | 14 / 14 | 25 / 16 | 99 / 20 | 6 / 6 | 94 / 9 |
| 018 | 1.24 GB | 8 / 11 | 21 / 14 | 14 / 16 | 24 / 18 | – | 6 / 6 | – |
| 019 | 359.2 MB | 6 / 11 | 19 / 14 | 13 / 15 | 25 / 18 | – | 6 / 6 | – |
| 020 | 1.85 GB | 9 / 11 | 22 / 14 | 13 / 16 | 25 / 18 | – | 6 / 6 | – |
| 021 | 67.7 MB | 5 / 11 | 19 / 14 | 14 / 16 | 25 / 17 | 100 / 21 | 6 / 6 | 94 / 9 |
| 022 | 223.9 MB | 6 / 11 | 19 / 14 | 14 / 16 | 25 / 18 | – | 6 / 6 | – |
| 023 | 1.09 GB | 6 / 11 | 20 / 14 | 13 / 16 | 25 / 18 | – | 6 / 6 | – |
| 024 | 1.20 GB | 7 / 11 | 21 / 14 | 13 / 16 | 25 / 18 | – | 6 / 6 | – |
| 025 | 1.79 GB | 8 / 11 | 22 / 14 | 14 / 16 | 25 / 18 | – | 6 / 6 | – |
| 026 | 1.79 GB | 8 / 11 | 22 / 14 | 13 / 16 | 25 / 17 | – | 6 / 6 | – |
| 027 | 237.9 MB | 6 / 11 | 19 / 14 | 13 / 16 | 25 / 17 | – | 6 / 6 | – |
| 028 | 2.52 GB | 10 / 11 | 23 / 14 | 13 / 16 | 25 / 18 | – | 6 / 6 | – |
| 029 | 375.7 MB | 6 / 11 | 19 / 14 | 13 / 16 | 25 / 17 | – | 6 / 6 | – |

## Limits and caveats

- pack accepts only fixed-width line files. In the black-box review on public data, it refused 31 of 32 public files (Silesia, Canterbury, logs, images, archives) with exit code 1. On `ptt5`, the one file it accepted, its output was 17% larger than zstd9. It has no built-in zstd fallback.
- pack compression memory is about 512 B × column count, so very wide single-line inputs need gigabytes. A 10 MB single-line file needed about 5 GB and failed with "out of memory" when RAM was short. This is not fixed.
- Before the fix, 39 of 50 random bit flips in a pack file decoded with exit code 0 to wrong data. After the fix, 0 of 427 damaged files did. Files written by the old binary still decode, but they have no checksum.
- Decompression times include writing up to 2.5 GB to disk, so they are partly disk-bound.
- Only the `.vec` round trip is tested. The `.pat` zip (Program.sprg, Comments.cmt) is not rebuilt.
- Single machine, single run per point, no repeats. Treat speed differences under about 10% as noise.

Raw data: `bench-hackathon-blackbox.csv` (next to this file).

## Average compression (efficiency factor)

Efficiency factor = (sum of all original `.vec` bytes) / (sum of all compressed bytes), per algorithm. This is size-weighted, not the mean of the per-file ratios.

### All 29 files (24,440,836,216 B original)

| algorithm | compressed sum | Average compression | vs zstd9 |
|---|---:|---:|---:|
| Average compression - pack1 | 814,933,574 B | **29.99x** | 2.14x smaller |
| Average compression - pack9 | 808,661,747 B | **30.22x** | 2.15x smaller |
| Average compression - zstd9 (baseline) | 1,740,586,211 B | **14.04x** | baseline |

### The 8 files zstd19 ran on (001, 002, 012, 013, 015, 016, 017, 021; 123,853,288 B original)

zstd19 ran only on files under 100 MB, so it is compared on that subset only.

| algorithm | compressed sum | Average compression | vs zstd19 |
|---|---:|---:|---:|
| Average compression - pack1 | 1,755,997 B | **70.53x** | 1.67x smaller |
| Average compression - pack9 | 1,686,461 B | **73.44x** | 1.74x smaller |
| Average compression - zstd9 (baseline) | 4,694,150 B | **26.38x** | 1.60x larger |
| Average compression - zstd19 | 2,933,623 B | **42.22x** | – |

## Average decompression speed

Average decompression speed = (sum of all original `.vec` bytes) / (sum of all decompress wall times), per algorithm. MB = 10^6 B. Times include writing the output to disk.

### All 29 files (24,440,836,216 B, decompressed)

| algorithm | total decompress time | Average decompression speed | vs zstd9 |
|---|---:|---:|---:|
| Average decompression - pack1 | 82.8 s | **295.0 MB/s** | 1.22x faster |
| Average decompression - pack9 | 78.5 s | **311.4 MB/s** | 1.29x faster |
| Average decompression - zstd9 (baseline) | 101.0 s | **242.1 MB/s** | baseline |

### zstd19 comparison: files 012 and 021 (109,413,760 B)

zstd19 ran only on files under 100 MB, and six of those eight are under 5 MB. On a file that small, the roughly 0.12 s Python start-up of each zstd run takes up most of the time measured. So the zstd19 comparison uses only 012 (41.7 MB) and 021 (67.7 MB).

| algorithm | total decompress time | Average decompression speed | vs zstd19 |
|---|---:|---:|---:|
| Average decompression - pack1 | 0.342 s | **319.9 MB/s** | 1.55x faster |
| Average decompression - pack9 | 0.312 s | **350.7 MB/s** | 1.70x faster |
| Average decompression - zstd9 (baseline) | 0.596 s | **183.6 MB/s** | 1.12x slower |
| Average decompression - zstd19 | 0.530 s | **206.4 MB/s** | – |
