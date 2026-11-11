# CLAUDE.md: tests/Split

Local sub-task of the main challenge (see `../../CLAUDE.md`): split vectors into drive (`0 1 X`) and read (`L H X`) column streams and zstd each one separately.

## Tool: `split.c`
- Build: `gcc -O2 split.c -o split.exe libzstd.dll`. `libzstd.dll` is copied here.
- `split.exe [level=9] [in.vec] [outdir]` splits, compresses each part, rebuilds from the compressed parts, compares the result byte for byte with the input, and prints the benchmark.
- `split.exe -x <level> <dir> <out.vec>` rebuilds from `vectors_{map,drive,read,anomaly}_<level>.compr`.
- `split.exe --selftest` runs the asserts (anomalies, CRLF, missing final newline, bad width).

## Decisions (user)
- Column type is decided by **majority**: drive if count(0/1) ≥ count(L/H). X-only columns count as drive.
- A cell of the other type (or any unknown byte) is **removed** from its stream and recorded in `vectors.anomaly`, a binary file of `varint row delta, varint col, char` records. Rebuild inserts the anomalies **last**.
- Output is **separate files** for now, to make inspection easy.
- The zstd level is a parameter (any level); the default is **9**.

## Results (001, 20,072 B)
| level | whole-file zstd | split total (map+drive+read+anomaly) | gain |
|---|---|---|---|
| 9 | 736 B | 547 B (35+236+267+9) | 1.35x |
| 19 | 547 B | 417 B (35+173+200+9) | 1.31x |
- 001 has 0 anomalies: every column is purely drive (96) or purely read (96).
- The fixed overheads (map 35 B, plus 9 B for the empty zstd frame of the anomaly file) are about 8–10% of the total here. On large files they are negligible.

## Corpus benchmark: files 001–005, zstd level 9, single thread, both methods streamed (2026-11-10)
The tool is now fully streaming: the input is memory-mapped and processed in 4 MB row blocks, so memory stays constant. Decompression is timed with the output discarded, then verified in a separate pass against the original.

| file | size | pins (drive/read) | zstd | split | gain | decomp zstd → split MB/s | lost bytes |
|---|---|---|---|---|---|---|---|
| 001 | 20 KB | 96/96 | 769 B | 559 B | 1.38x | 77 → 42 (noise) | 0/0 |
| 002 | 4.1 MB | 5/0 | 20,930 B | 20,994 B | 0.997x | 1016 → 214 | 0/0 |
| 003 | 2.50 GB | 76/0 | 296.07 MB (8.44x) | +1 KB | 1.000x | 387 → 347 | 0/0 |
| 004 | 1.44 GB | drive only | 160.39 MB (8.99x) | +0.6 KB | 1.000x | 514 → 470 | 0/0 |
| 005 | 1.43 GB | drive only | 153.62 MB (9.34x) | +0.6 KB | 1.000x | 482 → 395 | 0/0 |

- **Finding: 002–005 contain only `0 1 X` (no expects)**, so the split has nothing to separate. It equals zstd plus about 1 KB of overhead (map + empty anomaly frame + a read stream of bare newlines) and decompresses 10–20% slower because of the rebuild pass. It helps only files that mix drive and read pins, like 001.
- Compression speed at L9 is about 20 MB/s for both methods (zstd dominates). 0 anomalies in all files.
- The big files are dense `0/1` scan data at about 8.5–9.3x. That is the hard case, and it dominates the corpus by size.
- Earlier synthetic test (the 001 sample repeated, ratios meaningless): 20 MB split at about 210 MB/s. Injected anomalies (3 cells, including an unknown `?`) round-trip byte-identical.

## Ideas / next
- [x] Streaming / row-block processing, so memory stays constant.
- [ ] Skip the split when there are no read columns (removes the overhead and the slowdown on drive-only files).
- [ ] Find structure in the dense drive-only scan data (003–005): column-wise layout, bit-packing of `0/1/X`, GF(2)/LFSR modelling.
- [ ] Put everything in one container, with the map and anomalies stored raw in the header (saves about 40 B per file).
- [ ] Store each stream column by column, or split it into X-mask and value layers, then zstd.
