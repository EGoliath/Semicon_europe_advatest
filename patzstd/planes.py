"""
`planes` mode: container v3 with full-length per-pin bit-planes, pin aliasing
and independent zstd frames cut by PIN GROUP (parallel compression and
decompression without losing the long per-pin context).

Ideas from the "split bit-planes" report, kept only where tools/recon.py and
tools/explore_v3.py showed they pay on the real corpus (results/IDEAS.md §10):

* pin-major bit-planes, 1 bit per vector for 2-symbol pins;
* each pin's time series is contiguous over a whole SEGMENT (16 Mi vectors,
  i.e. the whole file for 27/29 files) instead of 1 Mi-vector chunks:
  5-6% smaller at every zstd level;
* frames are cut by pin group, not by rows: pins compress independently with
  no measurable loss, so a segment yields many independent frames that are
  (de)compressed in parallel;
* 3-symbol pins (H/L/X) are split into a MASK plane (symbol == a2, normally X)
  and a VALUE plane (symbol == a1) instead of 5-per-byte ternary;
* duplicate, inverted and (per segment) constant pins cost 0 bits.
  bit = (symbol != the pin's first-row symbol), so every bit stream starts with
  0 and a complementary pin (L/H mirror of 0/1) has an IDENTICAL bit stream:
  one exact byte comparison catches duplicates and inverses.

Measured and NOT built (< 0.1% on this corpus): period-aligned XOR, run lengths
for slow pins, clock descriptors, zstd windows > 128 MiB, cross-file dedup.

Format (little-endian; the file is NOT wrapped in an outer zstd stream):

    MAGIC3  b"PZST\\x03"
    u32     member count
    member: u16 name_len, name (utf-8), u8 mode (6 planes | 7 zraw), u64 size,
            u8 codec (0 stored, 1 zstd, 2 xz/LZMA2 -- archive tier)
      planes: u32 W, u64 rows, u32 S (vectors per segment, multiple of 8)
              META(W x (u8 cls, u8 a0, u8 a1, u8 a2))   cls 0 const, 1 binary, 2 ternary
              u32 nseg = ceil(rows / S)
              per segment (r vectors, nb = ceil(r/8)):
                  u32 ngroups
                  META(W x u32 map, ngroups x (u32 nstreams, u64 comp_len))
                                 map, binary pins: 0xFFFFFFFF stored, 0xFFFFFFFE all 0,
                                 0xFFFFFFFD all 1, j < c: same bits as binary pin j;
                                 0 for const / ternary pins
                  frames         frame g = streams of group g, nb bytes each
              The stream list of a segment is, pins in order: a stored binary pin
              -> its bits; a ternary pin -> mask plane, then value plane.
              Groups take consecutive streams. Bits are MSB-first, earliest vector
              first. Binary symbol = a0 if bit 0 else a1; ternary: mask -> a2,
              else value -> a1, else a0 (mask and value both set is invalid).
      zraw:   u32 F (raw bytes per frame), u32 nframes, nframes x u64 comp_len, frames
      16 B    xxh3_128(xxh3_128(original bytes) || xxh3_128(every metadata byte of the
              record: header from name_len on, W/rows/S, META blobs, counts, frame
              index)) -- frames themselves are verified through the decoded bytes
    META(x) = u32 len + x, zstd-compressed unless codec = 0 (then stored).
"""

import lzma
import os
import queue
import struct
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import xxhash
import zstandard as zstd

from . import fast

MAGIC3 = b"PZST\x03"
MODE_PLANES, MODE_ZRAW = 6, 7
CODEC_STORED, CODEC_ZSTD, CODEC_XZ = 0, 1, 2
STORED, ZERO, ONES = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD
CLS_CONST, CLS_BIN, CLS_TER = 0, 1, 2
DEFAULT_SEG_ROWS = 1 << 24            # 16 Mi vectors = 2 MiB per pin and segment
GROUP_BYTES = 2 << 20                 # target raw bytes per frame (8 MiB: -1..2% at L19/xz, 2x slower)
UNPACK_ROWS = 1 << 20                 # decoder output block
ZRAW_FRAME = 32 << 20
HASH_LEN = 16


class PlanesError(Exception):
    pass


def _workers(threads):
    return threads if threads and threads > 0 else os.cpu_count()


def _compress(level, raw, codec=CODEC_ZSTD):
    if level is None or codec == CODEC_STORED:
        return raw
    if codec == CODEC_XZ:
        preset = min(max(level, 0), 9) | (lzma.PRESET_EXTREME if level >= 9 else 0)
        return lzma.compress(raw, format=lzma.FORMAT_XZ, check=lzma.CHECK_NONE, preset=preset)
    p = zstd.ZstdCompressionParameters.from_level(level, source_size=len(raw), threads=0)
    return zstd.ZstdCompressor(compression_params=p).compress(raw)


def _meta_out(level, raw):
    """Small metadata blob (pin table, segment map + group table): u32 len + bytes."""
    b = _compress(level if level is None else min(max(level, 3), 19), raw)    # always zstd
    return struct.pack("<I", len(b)) + b


def _meta_in(fin, codec, n, hm):
    (ln,) = struct.unpack("<I", _needm(fin, 4, hm))
    if ln > 16 * n + 64:
        raise PlanesError("bad metadata length")
    return _decompress(CODEC_STORED if codec == CODEC_STORED else CODEC_ZSTD, _needm(fin, ln, hm), n)


def _final(h, hm):
    """Stored checksum: xxh3-128 over (data digest, metadata digest)."""
    return xxhash.xxh3_128(h.digest() + hm.digest()).digest()


def _decompress(codec, comp, n):
    if codec == CODEC_STORED:
        raw = comp
    elif codec == CODEC_XZ:
        try:
            d = lzma.LZMADecompressor(format=lzma.FORMAT_XZ)
            raw = d.decompress(comp, max_length=n + 1)
            if not d.eof or d.unused_data:
                raise PlanesError("bad xz frame")
        except lzma.LZMAError as e:
            raise PlanesError(f"corrupt frame: {e}") from None
    else:
        try:
            raw = zstd.ZstdDecompressor().decompress(comp, max_output_size=n)
        except zstd.ZstdError as e:
            raise PlanesError(f"corrupt frame: {e}") from None
    if len(raw) != n:
        raise PlanesError("frame length mismatch")
    return raw


# ------------------------------------------------------------------ analysis
def pin_table(W, pres, first):
    """Per-pin (cls, a0, a1, a2), or None when some pin uses > 3 symbols."""
    tab = np.zeros((W, 4), np.uint8)
    for c in range(W):
        s = np.flatnonzero(pres[c])
        if len(s) > 3:
            return None
        f = first[c]
        if len(s) == 1:
            tab[c] = (CLS_CONST, s[0], s[0], s[0])
        elif len(s) == 2:
            tab[c] = (CLS_BIN, f, s[0] if s[1] == f else s[1], 0)
        else:
            a2 = ord("X") if ord("X") in s else s[-1]          # mask symbol
            rest = [v for v in s if v != a2]
            tab[c] = (CLS_TER, rest[0], rest[1], a2)
    return tab


def _groups(n_streams, nb, group_bytes=None):
    per = max(1, (group_bytes or GROUP_BYTES) // max(nb, 1))
    out, i = [], 0
    while i < n_streams:
        k = min(per, n_streams - i)
        out.append((i, k))
        i += k
    return out


# ------------------------------------------------------------------- encoder
def _segment_streams(buf, r, W, tab, base):
    """(map, list of stream byte arrays) for one segment."""
    P = fast.pack(buf, r, W, base).reshape(W, -1)          # bit = symbol != a0
    nb = P.shape[1]
    ones = np.full(nb, 0xFF, np.uint8)
    if r % 8:
        ones[-1] = (0xFF << (8 - r % 8)) & 0xFF
    cmap = np.zeros(W, np.uint32)
    streams, seen, grid = [], {}, None
    for c in range(W):
        cls = tab[c, 0]
        if cls == CLS_BIN:
            x = P[c]
            if not x.any():
                cmap[c] = ZERO
                continue
            k = x.tobytes()
            if k in seen:                     # dict lookup = exact byte comparison
                cmap[c] = seen[k]
            elif np.array_equal(x, ones):
                cmap[c] = ONES
            else:
                seen[k] = c
                cmap[c] = STORED
                streams.append(x)
        elif cls == CLS_TER:
            if grid is None:
                grid = np.frombuffer(buf, np.uint8).reshape(r, W + 1)
            col = grid[:, c]
            streams.append(np.packbits(col == tab[c, 3]))
            streams.append(np.packbits(col == tab[c, 2]))
    return cmap, streams, nb


def write_member(fout, m, info, level, threads, seg_rows=DEFAULT_SEG_ROWS, xz=False,
                 group_bytes=None):
    """Write one member record. info = grid_info(m) or None. Returns report dict.
    xz=True: LZMA/xz frames (archive tier; level = xz preset 0-9, 9 = -9e)."""
    name = m.name.encode()
    codec = CODEC_STORED if level is None else CODEC_XZ if xz else CODEC_ZSTD
    h, hm = xxhash.xxh3_128(), xxhash.xxh3_128()       # original bytes / metadata

    def mw(b):                                         # metadata write (checksummed)
        hm.update(b)
        fout.write(b)
    tab = pin_table(info[0], info[2], info[3]) if info is not None else None
    view = m.view()
    if view is None:                                   # zip member or empty file
        with m.open() as f:
            view = memoryview(f.read())
    nw = _workers(threads)
    fast.set_threads(nw)
    head = struct.pack("<H", len(name)) + name
    hdr_of = lambda mode: head + struct.pack("<BQB", mode, m.size, codec)   # noqa: E731
    rep = {"name": m.name, "size": m.size}
    with ThreadPoolExecutor(nw) as ex:
        if tab is not None:
            W, rows = info[0], info[1]
            S = max(8, seg_rows // 8 * 8)
            stride = W + 1
            mw(hdr_of(MODE_PLANES))
            mw(struct.pack("<IQI", W, rows, S) + _meta_out(level, tab.tobytes()))
            nseg = (rows + S - 1) // S
            mw(struct.pack("<I", nseg))
            base = np.ascontiguousarray(tab[:, 1])
            stored = aliased = zero = 0
            for r0 in range(0, rows, S):
                r = min(S, rows - r0)
                buf = view[r0 * stride:(r0 + r) * stride]
                hj = ex.submit(h.update, buf)          # xxh3 releases the GIL
                cmap, streams, nb = _segment_streams(buf, r, W, tab, base)
                stored += int((cmap == STORED).sum())
                zero += int(((cmap == ZERO) | (cmap == ONES)).sum())
                aliased += int((cmap < W).sum() - (tab[:, 0] != CLS_BIN).sum())
                groups = _groups(len(streams), nb, group_bytes)
                futs = [ex.submit(lambda i=i, k=k: _compress(level, b"".join(
                    s.tobytes() for s in streams[i:i + k]), codec)) for i, k in groups]
                frames = [f.result() for f in futs]
                hj.result()
                mw(struct.pack("<I", len(groups)) + _meta_out(level, cmap.tobytes() + b"".join(
                    struct.pack("<IQ", k, len(fr)) for (_, k), fr in zip(groups, frames))))
                for fr in frames:
                    fout.write(fr)
            rep.update(mode="planes", segments=nseg, pin_streams_stored=stored,
                       pins_aliased=aliased, pins_zero_or_ones=zero,
                       pins_const=int((tab[:, 0] == 0).sum()), pins_ter=int((tab[:, 0] == 2).sum()))
        else:
            mw(hdr_of(MODE_ZRAW))
            offs = range(0, m.size, ZRAW_FRAME)
            futs = [ex.submit(_compress, level, bytes(view[o:o + ZRAW_FRAME]), codec) for o in offs]
            h.update(view)
            frames = [f.result() for f in futs]
            mw(struct.pack("<II", ZRAW_FRAME, len(frames)))
            mw(b"".join(struct.pack("<Q", len(fr)) for fr in frames))
            for fr in frames:
                fout.write(fr)
            rep.update(mode="zraw", frames=len(frames))
    fout.write(_final(h, hm))
    return rep


# ------------------------------------------------------------------- decoder
def _need(f, n):
    b = f.read(n)
    if len(b) != n:
        raise PlanesError("truncated file")
    return b


def _needm(f, n, hm):
    b = _need(f, n)
    hm.update(b)
    return b


def _stream_list(cmap, tab, W):
    """Stream owners of a segment, in payload order, after validating the map."""
    lst = []
    for c in range(W):
        cls = tab[c, 0]
        if cls == CLS_BIN:
            v = int(cmap[c])
            if v == STORED:
                lst.append((c, 0))
            elif v not in (ZERO, ONES) and not (v < c and tab[v, 0] == CLS_BIN and cmap[v] == STORED):
                raise PlanesError(f"bad pin map entry {v:#x} for pin {c}")
        elif cls == CLS_TER:
            lst += [(c, 1), (c, 2)]
    return lst


def _read_segment(fin, ex, codec, r, W, tab, hm):
    """Read and decompress one segment -> (P bits W x nb, ternary planes dict)."""
    nb = (r + 7) // 8
    (ng,) = struct.unpack("<I", _needm(fin, 4, hm))
    if ng > 2 * W:
        raise PlanesError("bad group count")
    meta = _meta_in(fin, codec, 4 * W + 12 * ng, hm)
    cmap = np.frombuffer(meta, np.uint32, W).copy()
    lst = _stream_list(cmap, tab, W)
    groups = [struct.unpack_from("<IQ", meta, 4 * W + 12 * i) for i in range(ng)]
    if sum(k for k, _ in groups) != len(lst) or any(k == 0 for k, _ in groups):
        raise PlanesError("stream count mismatch")
    futs = [ex.submit(_decompress, codec, _need(fin, clen), k * nb) for k, clen in groups]
    P = np.zeros((W, nb), np.uint8)
    ter = {}
    i = 0
    for f, (k, _) in zip(futs, groups):
        raw = f.result()
        for j in range(k):
            c, kind = lst[i]
            a = np.frombuffer(raw, np.uint8, nb, j * nb)
            if kind == 0:
                P[c] = a
            else:
                ter[(c, kind)] = a
            i += 1
    for c in range(W):
        if tab[c, 0] == CLS_BIN:
            v = int(cmap[c])
            if v == ONES:
                P[c] = 0xFF
            elif v < W:
                P[c] = P[v]
    return P, ter


def _unpack_block(P, ter, b0, r, W, tab):
    """Rows b0*8 .. b0*8+r of a segment -> grid bytes."""
    nb = (r + 7) // 8
    sub = np.ascontiguousarray(P[:, b0:b0 + nb])
    out = fast.unpack(sub.reshape(-1), r, W, np.ascontiguousarray(tab[:, 1]),
                      np.ascontiguousarray(tab[:, 2]))
    if ter:
        g = out.reshape(r, W + 1)
        for c in {c for c, _ in ter}:
            mask = np.unpackbits(ter[(c, 1)][b0:b0 + nb], count=r).astype(bool)
            val = np.unpackbits(ter[(c, 2)][b0:b0 + nb], count=r).astype(bool)
            if (mask & val).any():
                raise PlanesError("ternary pin: mask and value both set")
            g[:, c] = np.where(mask, tab[c, 3], np.where(val, tab[c, 2], tab[c, 1]))
    return out


def iter_members_v3(fin, threads=-1):
    """Yield (name, mode, size, emit) like codec.iter_members (fin at offset 0).
    emit(out) MUST be called for every member, in order."""
    if fin.read(len(MAGIC3)) != MAGIC3:
        raise PlanesError("not a .pzst v3 file")
    nw = _workers(threads)
    fast.set_threads(nw)
    (n,) = struct.unpack("<I", _need(fin, 4))
    for _ in range(n):
        nlb = _need(fin, 2)
        (nl,) = struct.unpack("<H", nlb)
        nameb = _need(fin, nl)
        tail = _need(fin, 10)
        mode, size, codec = struct.unpack("<BQB", tail)
        try:
            name = nameb.decode()
        except UnicodeDecodeError:
            raise PlanesError("corrupt member name") from None
        if codec not in (CODEC_STORED, CODEC_ZSTD, CODEC_XZ):
            raise PlanesError(f"{name}: unknown codec {codec}")
        if mode not in (MODE_PLANES, MODE_ZRAW):
            raise PlanesError(f"{name}: unknown mode {mode}")

        def emit(out, mode=mode, size=size, name=name, codec=codec, hdr=nlb + nameb + tail):
            h, hm = xxhash.xxh3_128(), xxhash.xxh3_128()
            hm.update(hdr)
            q = queue.Queue(maxsize=3)           # decoded blocks -> writer (this thread)
            err = []

            class _Q:                            # producer side: hash, then hand over
                @staticmethod
                def write(a):
                    h.update(a)
                    q.put(a)

            def produce():
                try:
                    _decode_member(fin, nw, mode, size, codec, _Q, hm)
                except BaseException as e:       # re-raised in the writer thread
                    err.append(e)
                finally:
                    q.put(None)

            t = threading.Thread(target=produce, daemon=True)
            t.start()
            try:
                while True:
                    a = q.get()
                    if a is None:
                        break
                    out.write(a)
            finally:
                while t.is_alive():              # unblock the producer on writer errors
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        t.join(0.01)
            if err:
                e = err[0]
                if isinstance(e, PlanesError):
                    raise PlanesError(f"{name}: {e}") from None
                raise e
            if _final(h, hm) != _need(fin, HASH_LEN):
                raise PlanesError(f"{name}: checksum mismatch - corrupted data")

        yield name, "planes" if mode == MODE_PLANES else "zraw", size, emit


def _decode_member(fin, nw, mode, size, codec, out, hm):
    """Decode one member's payload (after its fixed header) into out.write."""
    with ThreadPoolExecutor(nw) as ex:
        if mode == MODE_PLANES:
            W, rows, S = struct.unpack("<IQI", _needm(fin, 16, hm))
            if W == 0 or S == 0 or S % 8 or rows * (W + 1) != size:
                raise PlanesError("header size mismatch")
            tab = np.frombuffer(_meta_in(fin, codec, 4 * W, hm), np.uint8).reshape(W, 4).copy()
            if tab[:, 0].max(initial=0) > 2:
                raise PlanesError("bad pin class")
            (nseg,) = struct.unpack("<I", _needm(fin, 4, hm))
            if nseg != (rows + S - 1) // S:
                raise PlanesError("segment count mismatch")
            for r0 in range(0, rows, S):
                r = min(S, rows - r0)
                P, ter = _read_segment(fin, ex, codec, r, W, tab, hm)
                for q in range(0, r, UNPACK_ROWS):
                    out.write(_unpack_block(P, ter, q // 8, min(UNPACK_ROWS, r - q), W, tab))
        else:
            F, nf = struct.unpack("<II", _needm(fin, 8, hm))
            if F == 0 or nf != (size + F - 1) // F:
                raise PlanesError("frame count mismatch")
            lens = struct.unpack(f"<{nf}Q", _needm(fin, 8 * nf, hm))
            futs = [ex.submit(_decompress, codec, _need(fin, cl), min(F, size - i * F))
                    for i, cl in enumerate(lens)]
            for f in futs:
                out.write(f.result())
