# CLAUDE.md: tests/Visualization

Local sub-task of the main challenge (see `../../CLAUDE.md`).

## Scope
- Work only inside `tests/`. Input data: `tests/001-contents/` (the unpacked contents of `001.pat`).

## Data (001)
- `Vectors.vec`: 104 lines × 192 chars, LF line endings. Each line is one vector (cycle); each column is one pin. Characters seen: `0 1` (drive), `L H` (expect), `X` (don't care).
- `Program.sprg`: XML. `<Instrument id="P…,P…">` lists 192 pin IDs (one per column). The instruction sequence is `xmode=4`, `genVec 44`, `genVec 4` with `repeat=164`, `genVec 56`. The genVec values add up to 104 vectors, matching the lines in `.vec`.
- `Comments.cmt`: empty.

## Viewer: `vecview.c`
- Requirements (from the user): one vector = one grid row; colors `1`=white, `0`=black, `H`=red, `L`=green, `X`=purple; an interactive window showing the static final grid; written in C; **speed is the main concern**; inputs can be GBs.
- Design: Win32 GDI with no dependencies. The file is memory-mapped, and each frame samples only the visible pixels, so the cost is O(window size) whatever the file size. Lines must all be the same width.
- Build with `gcc -O2 vecview.c -o vecview.exe -lgdi32` (MinGW) or `cl /O2 vecview.c user32.lib gdi32.lib` (MSVC).
- Run `vecview.exe ..\001-contents\Vectors.vec [row:num,...]`; `vecview.exe --selftest` runs the asserts.
- Header bar (44 px): 1 B/cell, B/vector (line stride including EOL), vectors × pins, total size, and the history depth (back/forward), plus a color legend.
- **Instruction** category: yellow blocks in a 1-cell gutter left of pin 0, with the number drawn when it fits. The input is a placeholder argument, `row:num,...` (e.g. `0:44,44:4,48:56` for 001). **The real source is TBD (user).**
- `.compr` files (detected by the zstd magic) are stream-decompressed into a temp file that is deleted on close, then memory-mapped. A background thread re-runs the zstd match finder (`ZSTD_generateSequences`) at the level in `vector_<level>.compr` (default 3) and builds a literal/match bit mask. `C` toggles the overlay: literal cells are cyan, matched cells dimmed, and the header shows the literal share and the analysis progress. **It is a re-simulation, not decoded from the file**, and it restarts every 16 MB chunk. Build now also needs `libzstd.dll` (copied next to the exe).
- Measured: a 200 MB `.compr` (the repeated 001 sample) shows its window after 0.9 s, including decompression. The temp file was confirmed deleted after the process was killed.
- Finding (001, level 5): only 0.88% of bytes are literals; they sit in the first rows and at the start of the L/H section.
- View history: every pan, zoom or fit is recorded. Backspace or the mouse back button steps back; Shift+Backspace or the mouse forward button steps forward. A burst of wheel or arrow moves within 500 ms counts as one entry, and each direction keeps up to 256 entries.

## Goals
- [x] Visualize `Vectors.vec` as a pin × cycle map, with a color per state (`0 1 L H X`), to see where the redundancy is. Done in `vecview.c`. The self-test passes. Smoke test: a 1 GB synthetic file (5.2M rows) opens with an 18 MB working set because the file is mapped, not loaded.
- GCC (WinLibs 16.2, installed via winget) is not on PATH in older shells. Its location is `%LOCALAPPDATA%\Microsoft\WinGet\Packages\BrechtSanders.WinLibs.POSIX.UCRT_Microsoft.Winget.Source_8wekyb3d8bbwe\mingw64\bin`.
- [ ] Overlay the `Program.sprg` structure (genVec blocks, repeat) on the map.
- [ ] Note the patterns a compressor could exploit: repeated columns, periodic pins, constant runs, the row-to-row delta.

## Findings
_(append here)_
