# 04_pp_zstd_long — `pp:zstd19L`

Round 1 (xt). Per-pin bit planes, all planes in ONE zstd frame with long-distance matching and a window over the whole stream (up to 2 GiB). Fastest decompression of all tests.

## Measured result (full corpus: 29 files, 24.44 GB, 20 threads, i7-1370P, verified bit-exact 29/29)

| | size | ratio | size vs zstd -9 | compress MB/s | compress vs zstd -9 | decompress MB/s | decompress vs zstd -9 |
|---|---|---|---|---|---|---|---|
| `pp:zstd19L` | 732.5 MB | 33.4x | +57.9% smaller | 73 | -86% | 3197 | +164% |
| plain zstd -9 | 1740.7 MB | 14.0x | 0% | 505 | 0% | 1211 | 0% |

Speeds are vs zstd -9 measured by the same bench script (they were in-memory benchmarks; the
CLI below also includes Python start-up and file I/O, so re-measure with `evaluate.py`).

## Requirements

- Python 3.9+, `pip install -r requirements.txt`
- System: gcc, OpenMP, libzstd + headers (`zstd.h`, e.g. `dnf install libzstd-devel` / `apt install libzstd-dev`)

## Usage

```bash
pip install -r requirements.txt
python compress.py 001.pat 006.pat -o out            # -> out/001.pxt ...
python decompress.py out/*.pxt -o restored          # -> restored/001.pat/ (folder with the members)
python decompress.py out/*.pxt -o restored --as-pat # -> restored/001.pat (zip)
python evaluate.py /path/to/pat_files/               # compress + decompress + SHA-256 check + timing table
python evaluate.py /path/to/pat_files/ -- -l 9       # extra arguments after -- go to compress.py
```

Input: `.pat` zip archives or extracted `NNN.pat/` folders. Options: `-l 19` (default) or `-l 9` (777.3 MB, 1143 MB/s compress); `-T N` threads.
Every member is restored bit-exact and checked against a checksum stored in the file.
