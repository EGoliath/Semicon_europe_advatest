# `.pzst` container and ternary packing – binary format

All integers are little-endian. `u8/u16/u32/u64` = unsigned 8/16/32/64 bit.

## 1. Outer wrapper

A `.pzst` file is one of:

| first 4 bytes | meaning |
|---|---|
| `28 B5 2F FD` | the container below, wrapped in one zstd stream (normal case) |
| `50 5A 53 54` (`"PZST"`) | the container below, **not** compressed ("packing only", `level=None`) |
| anything else | rejected: `neither a zstd-wrapped nor a plain .pzst file` |

## 2. Container

```
magic      5 bytes  "PZST" 0x02
count      u32      number of members (Program.sprg, Vectors.vec, Comments.cmt, ...)
member[count]:
    name_len  u16
    name      name_len bytes, UTF-8 (decoder rejects '/', '..' etc. when writing to disk)
    mode      u8     0 raw | 1 transpose | 2 bitpack | 3 t5row | 4 mixed/t5col | 5 t5 stream
    size      u64    original member size in bytes
    header    mode specific (below)
    payload   mode specific (below), its length is derived from header fields
    hash      16 bytes xxh3-128 of the ORIGINAL member bytes
```

Member order, names and sizes are preserved, so the original files are
reconstructed byte for byte. Any unknown mode, impossible length or hash
mismatch is an error (`PzstError`) – the decoder never returns partial data
silently.

Modes 1–4 require the member to be a *grid*: `size = rows * (W + 1)` and every
line is exactly `W` symbols followed by `\n` (checked at compression time;
otherwise the member falls back to mode 5 or 0). The newlines are not stored;
the decoder regenerates them. Grid header for modes 1–4:

```
W      u32   symbols per vector (pins)
rows   u64   number of vectors
R      u32   vectors per chunk (default 1,048,576)
```
The payload is `ceil(rows / R)` chunks; the last chunk has `rows mod R` vectors.

## 3. Ternary group code (used by modes 3, 4, 5)

Five symbols with digits `d0..d4 ∈ {0,1,2}` (d0 = first symbol in order):

```
C = d0 + 3·d1 + 9·d2 + 27·d3 + 81·d4        0 ≤ C ≤ 242
decode: d_k = (C / 3^k) mod 3   (or a 243×5 lookup table)
```
An incomplete group of `k = 1..4` symbols uses the same formula with the
missing digits 0, so `C < 3^k`; a larger value is rejected.

## 4. Mode 5 – generic t5 stream (any bytes, e.g. XML or ragged text)

The member is cut into blocks of at most 1 MiB of original data:

```
block:
    type  u8      1 = RAW, 2 = T5        (anything else: error)
    n     u32     original bytes covered by this block (> 0, must fit the member)
    RAW:  n bytes copied verbatim
    T5:   m      u32       encoded length (≤ 2n + 16)
          alph   3 bytes   symbols for digit 0, 1, 2 (distinct, never '\n')
          data   m bytes   token stream
```
Blocks follow each other until `size` original bytes are produced.

Token stream (codes 243..255 are free because a full group needs only 0..242):

| token | meaning | bytes |
|---|---|---|
| `0..242` | full group of 5 alphabet symbols | 1 |
| `243` | newline `\n` | 1 |
| `244..247` | partial group of `k = token − 243` (1..4) symbols; next byte = C (< 3^k) | 2 |
| `248` | literal: next byte is copied (must not be `\n` or an alphabet symbol) | 2 |
| `249..255` | invalid → error | – |

Encoder: alphabet = 3 most frequent non-newline bytes of the block (padded
with unused byte values if fewer exist). A partial group is flushed whenever
a non-alphabet byte or the end of the block is reached. If `12 + m ≥ 5 + n`
the block is stored RAW instead (**raw fallback for blocks that grow**).
Decoded length must equal `n` exactly.

Overhead per line of W symbols: `⌈W/5⌉` groups, `+1` byte for a partial group
token when `W mod 5 ≠ 0`, `+1` byte newline token.

## 5. Mode 3 – t5row (grid, one alphabet for the file)

```
header: grid header + alph 3 bytes (digit 0,1,2; distinct, no '\n')
chunk of r vectors: r × G bytes, G = ⌈W/5⌉; vector v uses bytes v·G .. v·G+G−1,
                    group g covers symbols 5g .. 5g+4 of the line (last one partial)
```
Only possible when the whole member uses ≤ 3 distinct symbols.

## 6. Mode 4 – mixed / t5col (grid, pin-major, per-pin radix)

```
header: grid header
        cls   W bytes      per pin: 0 = constant, 1 = binary, 2 = ternary
        alph  W × 3 bytes  per pin: symbols for digit 0, 1, 2
chunk of r vectors: pins in order 0..W−1, pin c contributes
        cls 0: 0 bytes          (every vector = alph[c][0])
        cls 1: ⌈r/8⌉ bytes      bit 7 of byte j = vector 8j (MSB first), bit → alph[c][bit]
        cls 2: ⌈r/5⌉ bytes      ternary group code over vectors 5j..5j+4 of that pin
```
`mixed` chooses the class from the number of symbols the pin uses (1/2/3);
`t5col` forces class 2 for every pin (pure ternary, for comparison).
Pins with more than 3 symbols make the member fall back to mode 5.

## 7. Mode 2 – bitpack (existing, binary)

```
header: grid header + base W bytes + alt W bytes
chunk: W × ⌈r/8⌉ bytes, pin-major, bit = (symbol ≠ base[c]), MSB first
```

## 8. Verification

* Decoder: per-member xxh3-128 over the reconstructed bytes, plus length checks.
* Test bench: independent SHA-256 of each source file compared with the
  SHA-256 of the decoded stream, outside the timed section.

---

## 9. Container v3 – `planes` / `planesxz` (patzstd/planes.py)

Written by `--mode planes` (zstd frames) and `--mode planesxz` (xz/LZMA2 frames).
Unlike v1/v2, the file is **not** wrapped in an outer zstd stream: every payload
is cut into independent frames listed in an index, so frames are compressed and
decompressed in parallel and any segment can be decoded on its own.
The decoder recognises v3 by its first 5 bytes `50 5A 53 54 03` (`"PZST\x03"`).

```
magic   5 bytes  "PZST" 0x03
count   u32
member[count]:
    name_len u16, name, mode u8 (6 planes | 7 zraw), size u64,
    codec u8 (0 stored | 1 zstd | 2 xz)
    mode 6 (planes), member must be a grid of W-symbol lines, every pin <= 3 symbols:
        W u32, rows u64, S u32          S = vectors per segment, multiple of 8 (default 16 Mi)
        META(pin table: W x (cls u8, a0 u8, a1 u8, a2 u8))
                                        cls 0 constant (a0), 1 binary (a0 = first-row
                                        symbol, a1 = the other), 2 ternary (a2 = mask
                                        symbol, X if present)
        nseg u32 = ceil(rows / S)
        segment[nseg]  (r vectors, nb = ceil(r / 8)):
            ngroups u32
            META(map: W x u32, groups: ngroups x (nstreams u32, comp_len u64))
            frame[ngroups]               comp_len bytes each, raw = nstreams * nb bytes
    mode 7 (zraw), any bytes:
        F u32 (raw bytes per frame, default 32 MiB), nframes u32 = ceil(size / F)
        nframes x comp_len u64, frames
    hash 16 bytes
```

`META(x)` = `u32 len` + x, zstd-compressed unless codec = 0 (then stored).

**Pin map** (binary pins; entry is 0 for constant / ternary pins):

| value | meaning |
|---|---|
| `0xFFFFFFFF` | stored: the pin's bits are the next stream of the segment |
| `0xFFFFFFFE` | all bits 0 in this segment (pin = a0 throughout) |
| `0xFFFFFFFD` | all bits 1 in this segment (pin = a1 throughout) |
| `j < c` | same bits as pin j, which must be a stored binary pin |

Bits are `symbol != a0`, so every stream starts with 0 and a complementary pin
(e.g. `LH…` mirroring `10…`) has an identical bit stream and is caught by the
same alias entry. The encoder compares the streams byte for byte (no hashing).

**Stream order** of a segment: pins in order; a stored binary pin contributes
its bits; a ternary pin contributes its mask plane (`symbol == a2`) and then its
value plane (`symbol == a1`). Each stream is nb bytes, MSB = earliest vector.
Groups take consecutive streams (about 2 MiB raw per frame). Decoding: binary
symbol = a0 if bit 0 else a1; ternary = a2 if mask, else a1 if value, else a0;
mask and value both set is an error.

**Checksum**: `xxh3_128( xxh3_128(original member bytes) || xxh3_128(all metadata
bytes of the record) )`, where metadata is every byte of the record except the
frames and the hash itself (header from `name_len` on, W/rows/S, META blobs,
counts, frame index). Frames are verified through the bytes they decode to.
Every length, count, class, map entry and frame size is validated before use;
any mismatch is a `PzstError`. The test suite flips every byte of a v3 file
and checks that each flip is detected.
