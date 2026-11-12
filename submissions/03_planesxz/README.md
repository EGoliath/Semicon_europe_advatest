# 03_planesxz — `planesxz:6`

Per-pin bit planes (v3 container), frames compressed with xz/LZMA. Best size among the codecs that still decompress faster than zstd -9.

## Measured result (full corpus: 29 files, 24.44 GB, 20 threads, i7-1370P, verified bit-exact 29/29)

| | size | ratio | size vs zstd -9 | compress MB/s | compress vs zstd -9 | decompress MB/s | decompress vs zstd -9 |
|---|---|---|---|---|---|---|---|
| `planesxz:6` | 700.2 MB | 34.9x | +59.8% smaller | 270 | +29% | 781 | +34% |
| plain zstd -9 | 1740.7 MB | 14.0x | 0% | 210 | 0% | 583 | 0% |

Speeds are vs zstd -9 measured by the same bench script (they were in-memory benchmarks; the
CLI below also includes Python start-up and file I/O, so re-measure with `evaluate.py`).

## Requirements

- Python 3.9+, `pip install -r requirements.txt`
- System: gcc recommended (builds `patzstd/libpatk.so`)

## Usage

```bash
pip install -r requirements.txt
python compress.py 001.pat 006.pat -o out            # -> out/001.pzst ...
python decompress.py out/*.pzst -o restored          # -> restored/001.pat/ (folder with the members)
python decompress.py out/*.pzst -o restored --as-pat # -> restored/001.pat (zip)
python evaluate.py /path/to/pat_files/               # compress + decompress + SHA-256 check + timing table
python evaluate.py /path/to/pat_files/ -- -l 9       # extra arguments after -- go to compress.py
```

Input: `.pat` zip archives or extracted `NNN.pat/` folders. Options: `-l 6` (default) or `-l 9` (699.4 MB, slower compress); `-T N` threads.
Every member is restored bit-exact and checked against a checksum stored in the file.
