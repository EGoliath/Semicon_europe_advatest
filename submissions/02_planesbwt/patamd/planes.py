"""
AMD EPYC versions of the `planes` family: container v4 (copy of patzstd/planes.py
v3, which is left untouched).

Same transform as v3 (full-length per-pin bit-planes, pin aliasing, H/L/X mask +
value planes, independent frames, xxh3-128), plus what the AMD research note and
the measurements in results/IDEAS.md section 11 asked for:

* a codec byte PER FRAME, so one file can mix back ends:
      1 zstd, 2 xz/LZMA2, 3 pcm (new context-mixing bit coder, patamd/cm.c),
      4 bzip3 (BWT family, the research note's "ratio first" class)
* pcm frames hold ONE pin stream each (a fresh model per pin measured 5.5% smaller
  than shared 2 MiB frames) and carry a per-stream lag for the pcm lag model;
  one frame per pin is also the natural unit for 64 EPYC cores;
* xz frames use a dictionary sized to the frame (the -9e preset allocates a 64 MiB
  dictionary, ~674 MiB of encoder memory, for a 2 MiB frame: 64 workers x 674 MiB
  would not fit; output size is unchanged);
* CPU profiles (patamd/cpu.py): `st` = one thread in total, pinned to one core;
  `mt` = worker threads pinned round-robin over the L3 domains (CCDs).

Format (little-endian):

    MAGIC4  b"PZST\\x04"
    u32     member count
    member: u16 name_len, name (utf-8), u8 mode (6 planes | 7 zraw), u64 size, u8 flags (0)
      planes: u32 W, u64 rows, u32 S
              META(W x (u8 cls, u8 a0, u8 a1, u8 a2))
              u32 nseg
              per segment:
                  u32 ngroups
                  META(W x u32 map,
                       ngroups x (u32 nstreams, u64 comp_len, u8 codec, u8 level),
                       nstreams_total x u32 lag)          lag only used by pcm frames
                  frames
      zraw:   u32 F, u32 nframes, META(nframes x (u64 comp_len, u8 codec, u8 level)), frames
      16 B    xxh3_128(xxh3_128(original) || xxh3_128(metadata))
    META(x) = u32 len + zstd(x)   (metadata is always zstd-compressed)

Stream order, pin map, bit order and symbol mapping are exactly as in v3.
"""

import lzma
import queue
import struct
import threading

import numpy as np
import xxhash
import zstandard as zstd

from . import cpu, fast

MAGIC4 = b"PZST\x04"
MODE_PLANES, MODE_ZRAW = 6, 7
CODEC_STORED, CODEC_ZSTD, CODEC_XZ, CODEC_PCM, CODEC_BZ3 = 0, 1, 2, 3, 4
STORED, ZERO, ONES = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD
CLS_CONST, CLS_BIN, CLS_TER = 0, 1, 2
DEFAULT_SEG_ROWS = 1 << 24
GROUP_BYTES = 2 << 20
UNPACK_ROWS = 1 << 20
ZRAW_FRAME = 32 << 20
HASH_LEN = 16
BZ3_BLOCK = 16 << 20


class PlanesError(Exception):
    pass


# ------------------------------------------------------------------ back ends
def _xz_filters(level, n):
    preset = min(max(level, 0), 9) | (lzma.PRESET_EXTREME if level >= 9 else 0)
    d = 1 << 16
    while d < n and d < (64 << 20):
        d <<= 1
    return [{"id": lzma.FILTER_LZMA2, "preset": preset, "dict_size": d}]


def _compress(codec, level, raw, lag=None, nb=0):
    if codec == CODEC_STORED:
        return raw
    if codec == CODEC_XZ:
        return lzma.compress(raw, format=lzma.FORMAT_XZ, check=lzma.CHECK_NONE,
                             filters=_xz_filters(level, len(raw)))
    if codec == CODEC_PCM:
        return fast.pcm_encode(raw, nb, len(raw) // nb, lag, level)
    if codec == CODEC_BZ3:
        import bz3
        return bz3.compress(bytes(raw), block_size=BZ3_BLOCK)
    p = zstd.ZstdCompressionParameters.from_level(level, source_size=len(raw), threads=0)
    return zstd.ZstdCompressor(compression_params=p).compress(raw)


def _decompress(codec, level, comp, n, lag=None, nb=0):
    try:
        if codec == CODEC_STORED:
            raw = comp
        elif codec == CODEC_XZ:
            d = lzma.LZMADecompressor(format=lzma.FORMAT_XZ)
            raw = d.decompress(comp, max_length=n + 1)
            if not d.eof or d.unused_data:
                raise PlanesError("bad xz frame")
        elif codec == CODEC_PCM:
            if nb == 0 or n % nb or level not in (1, 2, 3):
                raise PlanesError("bad pcm frame header")
            raw = fast.pcm_decode(comp, nb, n // nb, lag, level)
        elif codec == CODEC_BZ3:
            import bz3
            raw = bz3.decompress(comp)
        elif codec == CODEC_ZSTD:
            raw = zstd.ZstdDecompressor().decompress(comp, max_output_size=n)
        else:
            raise PlanesError(f"unknown frame codec {codec}")
    except (lzma.LZMAError, zstd.ZstdError, ValueError, RuntimeError) as e:
        raise PlanesError(f"corrupt frame: {e}") from None
    if len(raw) != n:
        raise PlanesError("frame length mismatch")
    return raw


def _meta_out(raw):
    b = zstd.ZstdCompressor(level=19).compress(raw)
    return struct.pack("<I", len(b)) + b


def _meta_in(fin, n, hm, exact=True):
    (ln,) = struct.unpack("<I", _needm(fin, 4, hm))
    if ln > 16 * n + 64:
        raise PlanesError("bad metadata length")
    try:
        raw = zstd.ZstdDecompressor().decompress(_needm(fin, ln, hm), max_output_size=n)
    except zstd.ZstdError as e:
        raise PlanesError(f"corrupt metadata: {e}") from None
    if exact and len(raw) != n:
        raise PlanesError("metadata length mismatch")
    return raw


def _final(h, hm):
    return xxhash.xxh3_128(h.digest() + hm.digest()).digest()


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
            a2 = ord("X") if ord("X") in s else s[-1]
            rest = [v for v in s if v != a2]
            tab[c] = (CLS_TER, rest[0], rest[1], a2)
    return tab


def _groups(n_streams, nb, codec, group_bytes=None):
    if codec == CODEC_PCM:                       # one frame per pin stream
        return [(i, 1) for i in range(n_streams)]
    per = max(1, (group_bytes or GROUP_BYTES) // max(nb, 1))
    return [(i, min(per, n_streams - i)) for i in range(0, n_streams, per)]


# ------------------------------------------------------------------- encoder
def _segment_streams(buf, r, W, tab, base):
    """(map, list of stream byte arrays) for one segment (identical to v3)."""
    P = fast.pack(buf, r, W, base).reshape(W, -1)
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
            if k in seen:
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


def write_member(fout, m, info, codec, level, profile, seg_rows=DEFAULT_SEG_ROWS, group_bytes=None):
    """Write one member record. codec: CODEC_* id; profile: cpu.Profile."""
    name = m.name.encode()
    h, hm = xxhash.xxh3_128(), xxhash.xxh3_128()

    def mw(b):
        hm.update(b)
        fout.write(b)
    tab = pin_table(info[0], info[2], info[3]) if info is not None else None
    view = m.view()
    if view is None:
        with m.open() as f:
            view = memoryview(f.read())
    fast.set_threads(profile.workers)
    head = struct.pack("<H", len(name)) + name
    hdr_of = lambda mode: head + struct.pack("<BQB", mode, m.size, 0)   # noqa: E731
    rep = {"name": m.name, "size": m.size}
    with cpu.executor(profile) as ex:
        if tab is not None:
            W, rows = info[0], info[1]
            S = max(8, seg_rows // 8 * 8)
            stride = W + 1
            mw(hdr_of(MODE_PLANES))
            mw(struct.pack("<IQI", W, rows, S) + _meta_out(tab.tobytes()))
            nseg = (rows + S - 1) // S
            mw(struct.pack("<I", nseg))
            base = np.ascontiguousarray(tab[:, 1])
            stored = 0
            for r0 in range(0, rows, S):
                r = min(S, rows - r0)
                buf = view[r0 * stride:(r0 + r) * stride]
                hj = ex.submit(h.update, buf)
                cmap, streams, nb = _segment_streams(buf, r, W, tab, base)
                stored += int((cmap == STORED).sum())
                lags = ([fast.pick_lag(s) for s in streams] if codec == CODEC_PCM
                        else [0] * len(streams))
                groups = _groups(len(streams), nb, codec, group_bytes)
                futs = [ex.submit(_compress, codec, level,
                                  b"".join(s.tobytes() for s in streams[i:i + k]), lags[i:i + k], nb)
                        for i, k in groups]
                frames = [f.result() for f in futs]
                hj.result()
                mw(struct.pack("<I", len(groups)) + _meta_out(
                    cmap.tobytes()
                    + b"".join(struct.pack("<IQBB", k, len(fr), codec, level & 0xFF)
                               for (_, k), fr in zip(groups, frames))
                    + np.asarray(lags, np.uint32).tobytes()))
                for fr in frames:
                    fout.write(fr)
            rep.update(mode="planes", segments=nseg, pin_streams_stored=stored,
                       pins_const=int((tab[:, 0] == 0).sum()), pins_ter=int((tab[:, 0] == 2).sum()))
        else:
            mw(hdr_of(MODE_ZRAW))
            # pcm models bit planes only; other members (XML, comments) use zstd -19
            zc, zl = (CODEC_ZSTD, 19) if codec == CODEC_PCM else (codec, level)
            offs = range(0, m.size, ZRAW_FRAME)
            futs = [ex.submit(_compress, zc, zl, bytes(view[o:o + ZRAW_FRAME])) for o in offs]
            h.update(view)
            frames = [f.result() for f in futs]
            mw(struct.pack("<II", ZRAW_FRAME, len(frames)) + _meta_out(
                b"".join(struct.pack("<QBB", len(fr), zc, zl) for fr in frames)))
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


def _read_segment(fin, ex, r, W, tab, hm):
    nb = (r + 7) // 8
    (ng,) = struct.unpack("<I", _needm(fin, 4, hm))
    if ng > 2 * W:
        raise PlanesError("bad group count")
    cap = 4 * W + 14 * ng + 8 * W                # map + groups + at most 2W lags
    meta = _meta_in(fin, cap, hm, exact=False)
    if len(meta) < 4 * W + 14 * ng:
        raise PlanesError("metadata length mismatch")
    cmap = np.frombuffer(meta, np.uint32, W).copy()
    lst = _stream_list(cmap, tab, W)
    groups = [struct.unpack_from("<IQBB", meta, 4 * W + 14 * i) for i in range(ng)]
    if len(meta) != 4 * W + 14 * ng + 4 * len(lst):
        raise PlanesError("metadata length mismatch")
    lags = np.frombuffer(meta, np.uint32, len(lst), 4 * W + 14 * ng).astype(np.int32)
    if sum(g[0] for g in groups) != len(lst) or any(g[0] == 0 for g in groups):
        raise PlanesError("stream count mismatch")
    futs, i = [], 0
    for k, clen, codec, level in groups:
        if codec == CODEC_PCM and k != 1:
            raise PlanesError("pcm frame must hold one stream")
        futs.append(ex.submit(_decompress, codec, level, _need(fin, clen), k * nb, lags[i:i + k], nb))
        i += k
    P = np.zeros((W, nb), np.uint8)
    ter = {}
    i = 0
    for f, (k, _, _, _) in zip(futs, groups):
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


def _decode_member(fin, profile, mode, size, out, hm):
    with cpu.executor(profile) as ex:
        if mode == MODE_PLANES:
            W, rows, S = struct.unpack("<IQI", _needm(fin, 16, hm))
            if W == 0 or S == 0 or S % 8 or rows * (W + 1) != size:
                raise PlanesError("header size mismatch")
            tab = np.frombuffer(_meta_in(fin, 4 * W, hm), np.uint8).reshape(W, 4).copy()
            if tab[:, 0].max(initial=0) > 2:
                raise PlanesError("bad pin class")
            (nseg,) = struct.unpack("<I", _needm(fin, 4, hm))
            if nseg != (rows + S - 1) // S:
                raise PlanesError("segment count mismatch")
            for r0 in range(0, rows, S):
                r = min(S, rows - r0)
                P, ter = _read_segment(fin, ex, r, W, tab, hm)
                for q in range(0, r, UNPACK_ROWS):
                    out.write(_unpack_block(P, ter, q // 8, min(UNPACK_ROWS, r - q), W, tab))
        else:
            F, nf = struct.unpack("<II", _needm(fin, 8, hm))
            if F == 0 or nf != (size + F - 1) // F:
                raise PlanesError("frame count mismatch")
            meta = _meta_in(fin, 10 * nf, hm)
            ents = [struct.unpack_from("<QBB", meta, 10 * i) for i in range(nf)]
            futs = [ex.submit(_decompress, c, lv, _need(fin, cl), min(F, size - i * F))
                    for i, (cl, c, lv) in enumerate(ents)]
            for f in futs:
                out.write(f.result())


def iter_members_v4(fin, profile):
    """Yield (name, mode, size, emit) like patzstd.codec.iter_members (fin at
    offset 0). emit(out) MUST be called for every member, in order."""
    if fin.read(len(MAGIC4)) != MAGIC4:
        raise PlanesError("not a .pzst v4 file")
    fast.set_threads(profile.workers)
    (n,) = struct.unpack("<I", _need(fin, 4))
    for _ in range(n):
        nlb = _need(fin, 2)
        (nl,) = struct.unpack("<H", nlb)
        nameb = _need(fin, nl)
        tail = _need(fin, 10)
        mode, size, flags = struct.unpack("<BQB", tail)
        try:
            name = nameb.decode()
        except UnicodeDecodeError:
            raise PlanesError("corrupt member name") from None
        if mode not in (MODE_PLANES, MODE_ZRAW) or flags != 0:
            raise PlanesError(f"{name}: unknown mode {mode}")

        def emit(out, mode=mode, size=size, name=name, hdr=nlb + nameb + tail):
            h, hm = xxhash.xxh3_128(), xxhash.xxh3_128()
            hm.update(hdr)

            class _H:                            # hash, then hand over
                def __init__(self, sink):
                    self.sink = sink

                def write(self, a):
                    h.update(a)
                    self.sink.write(a)
            try:
                if profile.name == "st":         # one thread: decode straight into out
                    _decode_member(fin, profile, mode, size, _H(out), hm)
                else:
                    _pipelined(fin, profile, mode, size, _H, out, hm)
            except PlanesError as e:
                raise PlanesError(f"{name}: {e}") from None
            if _final(h, hm) != _need(fin, HASH_LEN):
                raise PlanesError(f"{name}: checksum mismatch - corrupted data")

        yield name, "planes" if mode == MODE_PLANES else "zraw", size, emit


def _pipelined(fin, profile, mode, size, H, out, hm):
    """mt: a decoder thread produces blocks, this thread writes them (as v3)."""
    q = queue.Queue(maxsize=3)
    err = []

    class _Q:
        @staticmethod
        def write(a):
            q.put(a)

    sink = H(_Q)

    def produce():
        try:
            _decode_member(fin, profile, mode, size, sink, hm)
        except BaseException as e:
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
        while t.is_alive():
            try:
                q.get_nowait()
            except queue.Empty:
                t.join(0.01)
    if err:
        raise err[0]
