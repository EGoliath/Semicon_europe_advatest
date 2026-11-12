# 05_bk_container — `bkA:19lg`

Round 2 (xt2). Block-indexed split-stream container: constant / duplicate / complement pins removed per block, stored planes split into independent pin-group zstd frames, (de)compressed in parallel.

## Measured result (full corpus: 29 files, 24.44 GB, 20 threads, i7-1370P, verified bit-exact 29/29)

| | size | ratio | size vs zstd -9 | compress MB/s | compress vs zstd -9 | decompress MB/s | decompress vs zstd -9 |
|---|---|---|---|---|---|---|---|
| `bkA:19lg` | 732.9 MB | 33.3x | +57.9% smaller | 247 | -52% | 2213 | +78% |
| plain zstd -9 | 1740.7 MB | 14.0x | 0% | 517 | 0% | 1245 | 0% |

Speeds are vs zstd -9 measured by the same bench script (they were in-memory benchmarks; the
CLI below also includes Python start-up and file I/O, so re-measure with `evaluate.py`).

## Requirements

- Python 3.9+, `pip install -r requirements.txt`
- System: gcc, OpenMP, libzstd + headers (`zstd.h`)

## Usage

```bash
pip install -r requirements.txt
python compress.py 001.pat 006.pat -o out            # -> out/001.pxt ...
python decompress.py out/*.pxt -o restored          # -> restored/001.pat/ (folder with the members)
python decompress.py out/*.pxt -o restored --as-pat # -> restored/001.pat (zip)
python evaluate.py /path/to/pat_files/               # compress + decompress + SHA-256 check + timing table
python evaluate.py /path/to/pat_files/ -- -l 9       # extra arguments after -- go to compress.py
```

Input: `.pat` zip archives or extracted `NNN.pat/` folders. Options: `-l 19` (default); `-l 9 --block 4` (780.2 MB, 994 MB/s); `-l 3 --block 4` (794.1 MB, 1485 MB/s); `--no-ldm`; `-T N` threads.
Every member is restored bit-exact and checked against a checksum stored in the file.
