"""
patzstd - lossless zstd-based codec for SmarTest (V93000) .pat pattern files.

A .pat file is a ZIP holding Program.sprg (XML), Vectors.vec (ASCII vectors,
one fixed-width line per vector, one char per pin) and Comments.cmt.

Container format (.pzst, version 2) -- everything lives inside ONE zstd stream:

    MAGIC  b"PZST\x02"
    u32    number of members
    per member:
        u16  name length, name (utf-8)
        u8   mode            0=raw 1=transpose 2=bitpack 3=t5row 4=mixed 5=t5stream
        u64  original size in bytes
        [mode 1-4]  u32 width W (pins), u64 rows, u32 chunk rows R
        [mode 2]    W bytes base symbol, W bytes alt symbol (per pin)
        [mode 3]    3 bytes file alphabet (digit 0,1,2)
        [mode 4]    W bytes pin class (0 const, 1 binary, 2 ternary),
                    W*3 bytes per-pin alphabet
        [mode 5]    sequence of blocks (see docs/FORMAT.md)
        payload     (length derivable from the header fields)
        16 bytes    xxh3-128 of the ORIGINAL member bytes

Vector transforms (applied per chunk of R vectors, newlines dropped):
    transpose : rows x W  ->  W x rows   (each pin's time series is contiguous)
    bitpack   : same, but every pin column holds at most 2 symbols, so each
                vector is stored as 1 bit per pin (bit=1 -> alt symbol).
Transforms run in C/OpenMP (kernels.c) with a numpy fallback.

The container is normally wrapped in zstd. With level=None it is written
unwrapped ("packing only"); the decoder tells the two apart by the first
4 bytes (zstd frame magic 28 B5 2F FD vs b"PZST").
Full byte-level specification: docs/FORMAT.md
"""

import io
import mmap
from concurrent.futures import ThreadPoolExecutor
import os
import struct
import zipfile

import numpy as np
import xxhash
import zstandard as zstd

from . import fast, planes, ternary

MAGIC = b"PZST\x02"
MODE_RAW, MODE_TRANSPOSE, MODE_BITPACK = 0, 1, 2
MODE_T5ROW, MODE_MIXED, MODE_T5S = 3, 4, 5
MODE_NAMES = {MODE_RAW: "raw", MODE_TRANSPOSE: "transpose", MODE_BITPACK: "bitpack",
              MODE_T5ROW: "t5row", MODE_MIXED: "mixed", MODE_T5S: "t5"}
FORCE_MODES = ("raw", "transpose", "bitpack", "t5", "t5row", "t5col", "mixed", "best", "planes", "planesxz")
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
T5_BLOCK = 1 << 20                    # t5 stream block (original bytes)
BLK_RAW, BLK_T5 = 1, 2
DEFAULT_CHUNK_ROWS = 1 << 20          # 1 Mi vectors per transform chunk
IO_BLOCK = 16 << 20                   # raw-mode streaming block
WINDOW_LOG = 27                       # 128 MiB: decodable with zstd defaults
HASH_LEN = 16


class PzstError(Exception):
    pass


def _hasher():
    return xxhash.xxh3_128()


# --------------------------------------------------------------------- inputs
class Member:
    """A named byte source. Files on disk are memory-mapped (zero copy);
    zip members are streamed (and re-opened for the second pass)."""

    def __init__(self, name, size, opener, path=None):
        self.name, self.size, self._opener, self.path = name, size, opener, path
        self._mm = None

    def open(self):
        return self._opener()

    def view(self):
        """memoryview of the whole member if it is a plain file, else None."""
        if self.path is None or self.size == 0:
            return None
        if self._mm is None:
            with open(self.path, "rb") as f:
                self._mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        return memoryview(self._mm)


def members_from_path(path):
    """Accept a .pat/.zip archive or a directory with the extracted members."""
    if os.path.isdir(path):
        names = sorted(os.listdir(path))
        order = ["Program.sprg", "Vectors.vec", "Comments.cmt"]
        names.sort(key=lambda n: (order.index(n) if n in order else 99, n))
        out = []
        for n in names:
            p = os.path.join(path, n)
            if os.path.isfile(p):
                out.append(Member(n, os.path.getsize(p), lambda p=p: open(p, "rb"), p))
        return out
    if zipfile.is_zipfile(path):
        zf = zipfile.ZipFile(path)
        return [Member(i.filename, i.file_size, lambda i=i: zf.open(i))
                for i in zf.infolist() if not i.is_dir()]
    raise PzstError(f"{path}: not a directory or zip/.pat archive")


def _read_exact(f, n):
    buf = f.read(n)
    if len(buf) == n:
        return buf
    parts = [buf]
    got = len(buf)
    while got < n:
        b = f.read(n - got)
        if not b:
            break
        parts.append(b)
        got += len(b)
    return b"".join(parts)


def _need(f, n):
    b = _read_exact(f, n)
    if len(b) != n:
        raise PzstError("truncated stream")
    return b


def _chunks(member, rows, W, chunk_rows):
    """Yield (row_count, buffer) for successive chunks of a vector member."""
    view = member.view()
    stride = W + 1
    if view is not None:
        for r0 in range(0, rows, chunk_rows):
            r = min(chunk_rows, rows - r0)
            yield r, view[r0 * stride:(r0 + r) * stride]
        return
    with member.open() as f:
        left = rows
        while left:
            r = min(chunk_rows, left)
            yield r, _need(f, r * stride)
            left -= r


# ------------------------------------------------------------------- analysis
def grid_info(member, chunk_rows=DEFAULT_CHUNK_ROWS):
    """(W, rows, presence map W x 256, first line) if the member is a grid of
    equal-width newline-terminated lines, else None."""
    with member.open() as f:
        first = f.readline()
    if not first.endswith(b"\n") or len(first) < 2:
        return None
    W = len(first) - 1
    if member.size % (W + 1):
        return None
    rows = member.size // (W + 1)
    pres = np.zeros((W, 256), np.uint8)
    for r, buf in _chunks(member, rows, W, max(chunk_rows, 1 << 22)):
        if not fast.analyse(buf, r, W, pres):
            return None
    return W, rows, pres, first


def analyse_vectors(member, chunk_rows=DEFAULT_CHUNK_ROWS, info=False):
    """Decide the best mode for a vector member.

    Returns (mode, width, rows, base, alt). Falls back to raw when the file is
    not a clean grid of equal-width, newline-terminated lines."""
    gi = grid_info(member, chunk_rows) if info is False else info
    if gi is None:
        return MODE_RAW, 0, 0, None, None
    W, rows, pres, first = gi
    nsym = pres.sum(1)
    if nsym.max() > 2:
        return MODE_TRANSPOSE, W, rows, None, None
    base = np.frombuffer(first[:W], np.uint8).copy()
    alt = base.copy()
    for c in np.flatnonzero(nsym == 2):
        s = np.flatnonzero(pres[c])
        alt[c] = s[0] if s[0] != base[c] else s[1]
    return MODE_BITPACK, W, rows, base, alt


# -------------------------------------------------------------------- encoder
def _compressor(level, threads, long_distance):
    params = zstd.ZstdCompressionParameters.from_level(
        level, threads=threads, enable_ldm=long_distance,
        window_log=WINDOW_LOG if long_distance else 0)
    return zstd.ZstdCompressor(compression_params=params)


class _Plain:
    """Context manager writing the container without zstd (packing only)."""

    def __init__(self, f):
        self.f = f

    def __enter__(self):
        return self.f

    def __exit__(self, *a):
        return False


def _t5s_encode_block(b):
    alph = ternary.stream_alphabet(b)
    enc = ternary.stream_encode(b, alph)
    if 12 + len(enc) < 5 + len(b):
        return (struct.pack("<BII", BLK_T5, len(b), len(enc)) + alph.tobytes(), enc)
    return (struct.pack("<BI", BLK_RAW, len(b)), b)          # raw fallback


def _write_t5_stream(m, w, h, threads):
    """Encode a member as t5 blocks, blocks encoded in parallel (C releases
    the GIL), written in order."""
    view = m.view()
    if view is not None:
        blocks = (view[o:o + T5_BLOCK] for o in range(0, m.size, T5_BLOCK))
        f = None
    else:
        f = m.open()
        blocks = iter(lambda: f.read(T5_BLOCK), b"")
    nw = threads if threads and threads > 0 else os.cpu_count()
    stats = [0, 0]
    with ThreadPoolExecutor(nw) as ex:
        batch = []

        def flush():
            for hdr, payload in ex.map(_t5s_encode_block, batch):
                stats[hdr[0] == BLK_RAW] += 1
                w.write(hdr)
                w.write(payload)
            batch.clear()

        for b in blocks:
            h.update(b)
            batch.append(b)
            if len(batch) >= 4 * nw:
                flush()
        flush()
    if f:
        f.close()
    return {"t5_blocks": stats[0], "raw_blocks": stats[1]}


def _write_member(w, m, mode, p, threads, chunk_rows):
    """Write one complete member record (header, payload, hash) to w."""
    W, rows = p["W"], p["rows"]
    extra = {}
    name = m.name.encode()
    w.write(struct.pack("<H", len(name)) + name + struct.pack("<BQ", mode, m.size))
    h = _hasher()
    if mode == MODE_T5S:
        extra = _write_t5_stream(m, w, h, threads)
    elif mode == MODE_RAW:
        view = m.view()
        if view is not None:
            for o in range(0, m.size, IO_BLOCK):
                b = view[o:o + IO_BLOCK]
                h.update(b)
                w.write(b)
        else:
            with m.open() as f:
                for b in iter(lambda: f.read(IO_BLOCK), b""):
                    h.update(b)
                    w.write(b)
    else:
        w.write(struct.pack("<IQI", W, rows, chunk_rows))
        if mode == MODE_BITPACK:
            w.write(p["base"].tobytes() + p["alt"].tobytes())
        elif mode == MODE_T5ROW:
            w.write(p["alph"].tobytes())
        elif mode == MODE_MIXED:
            w.write(p["cls"].tobytes() + p["palph"].tobytes())
        for r, buf in _chunks(m, rows, W, chunk_rows):
            h.update(buf)
            if mode == MODE_TRANSPOSE:
                w.write(fast.transpose(buf, r, W))
            elif mode == MODE_BITPACK:
                w.write(fast.pack(buf, r, W, p["base"]))
            elif mode == MODE_T5ROW:
                w.write(ternary.row_pack(buf, r, W, p["alph"]))
            else:
                w.write(ternary.mixed_pack(buf, r, W, p["cls"], p["plut"]))
    w.write(h.digest())
    return extra


def _best_candidates(m, chunk_rows):
    """Candidate encodings for the 'best' mode: the earlier auto choice
    (bitpack, or transpose if a pin has 3+ symbols) and mixed (if every pin
    has <= 3 symbols). Returns (gi, {label: (mode, params)}) or (None, {})."""
    gi = grid_info(m, chunk_rows)
    if gi is None:
        return None, {}
    W, rows, pres, _ = gi
    mode, _, _, base, alt = analyse_vectors(m, chunk_rows, info=gi)
    c = {MODE_NAMES[mode]: (mode, {"W": W, "rows": rows, "base": base, "alt": alt})}
    if pres.sum(1).max() <= 3:
        cls, palph, plut = ternary.pin_classes(pres)
        c["mixed"] = (MODE_MIXED, {"W": W, "rows": rows, "cls": cls, "palph": palph,
                                   "plut": plut})
    return gi, c


def _packed_size(mode, p, chunk_rows):
    W, rows = p["W"], p["rows"]
    tot = 0
    for r0 in range(0, rows, chunk_rows):
        r = min(chunk_rows, rows - r0)
        if mode == MODE_BITPACK:
            tot += W * ((r + 7) // 8)
        elif mode == MODE_TRANSPOSE:
            tot += W * r
        else:
            tot += ternary.mixed_size(r, p["cls"])
    return tot


def compress(src_path, dst_path, level=3, threads=-1, long_distance=True,
             force_mode=None, chunk_rows=DEFAULT_CHUNK_ROWS, seg_rows=None, group_bytes=None):
    """Compress a .pat (or extracted directory) into dst_path.

    level      : zstd level, or None to skip zstd (packing only).
    force_mode : None (auto) or one of FORCE_MODES:
        raw / transpose / bitpack  existing modes
        t5      generic ternary stream codec on EVERY member
        t5row   vector grid row-major ternary, one file alphabet (<= 3 symbols)
        t5col   pin-major ternary for every pin (per-pin alphabet <= 3)
        mixed   pin-major per-pin radix: constant 0 bit / binary / ternary
        planes  container v3 (patzstd/planes.py): full-length per-pin bit
                planes, pin aliasing, H/L/X mask+value planes, independent
                zstd frames per pin group -> parallel (de)compression
        planesxz  same container, xz/LZMA frames (archive tier, level = xz preset)
        best    hybrid: encode the vector file with the earlier auto choice
                (bitpack / transpose) AND mixed, keep the smaller result.
                Each candidate is compressed into its own zstd frame; the
                winning frame is copied into the output (frames concatenate).
      When a vector file is not eligible for t5row / t5col / mixed it falls
      back to the generic t5 stream codec (reported in the result).
    Returns a list of per-member dicts with name / mode / size."""
    if force_mode is not None and force_mode not in FORCE_MODES:
        raise PzstError(f"unknown mode {force_mode}")
    fast.set_threads(threads if threads and threads > 0 else os.cpu_count())
    members = members_from_path(src_path)
    report = []
    if force_mode in ("planes", "planesxz"):
        with open(dst_path, "wb") as fout:
            fout.write(planes.MAGIC3 + struct.pack("<I", len(members)))
            for m in members:
                gi = grid_info(m, chunk_rows) if m.name.lower().endswith(".vec") else None
                report.append(planes.write_member(
                    fout, m, gi, level, threads, xz=force_mode == "planesxz",
                    seg_rows=seg_rows or planes.DEFAULT_SEG_ROWS, group_bytes=group_bytes))
        return report
    fout = open(dst_path, "wb")
    w_ctx = (_Plain(fout) if level is None else
             _compressor(level, threads, long_distance).stream_writer(fout, closefd=False))
    with fout, w_ctx as w:
        w.write(MAGIC + struct.pack("<I", len(members)))
        for m in members:
            mode, W, rows, base, alt = MODE_RAW, 0, 0, None, None
            extra = {}
            is_vec = m.name.lower().endswith(".vec")
            if is_vec and force_mode == "best":
                gi, cands = _best_candidates(m, chunk_rows)
                if cands:
                    trial = {}
                    if level is None:              # packing only: compare sizes directly
                        win = min(cands, key=lambda k: _packed_size(*cands[k], chunk_rows))
                        ex = _write_member(w, m, cands[win][0], cands[win][1], threads, chunk_rows)
                    else:
                        frames = {}
                        for k, (md, p) in cands.items():
                            bio = io.BytesIO()
                            cw = _compressor(level, threads, long_distance).stream_writer(
                                bio, closefd=False)
                            with cw:
                                _write_member(cw, m, md, p, threads, chunk_rows)
                            frames[k] = bio.getvalue()
                            trial[f"trial_{k}"] = len(frames[k])
                        win = min(frames, key=lambda k: len(frames[k]))
                        w.flush(zstd.FLUSH_FRAME)  # end current frame ...
                        fout.write(frames[win])     # ... and append the winner as a frame
                        ex = {}
                    report.append({"name": m.name, "mode": f"best:{win}", "size": m.size,
                                   "width": gi[0], "rows": gi[1], **trial, **ex})
                    continue
                mode = MODE_RAW                    # not a grid: same as auto
            elif force_mode == "t5":
                mode = MODE_T5S
            elif is_vec and force_mode in ("t5row", "t5col", "mixed"):
                gi = grid_info(m, chunk_rows)
                mode = MODE_T5S
                if gi is not None:
                    W, rows, pres, _ = gi
                    if force_mode == "t5row":
                        syms = np.flatnonzero(pres.any(0))
                        if len(syms) <= 3:
                            mode = MODE_T5ROW
                            fill = [b for b in range(32, 127) if b not in syms]
                            alph = np.array((list(syms) + fill)[:3], np.uint8)
                    elif pres.sum(1).max() <= 3:
                        mode = MODE_MIXED
                        cls, palph, plut = ternary.pin_classes(pres, force_mode == "t5col")
                        extra = {"pins_const": int((cls == 0).sum()),
                                 "pins_bin": int((cls == 1).sum()),
                                 "pins_ter": int((cls == 2).sum())}
            elif is_vec and force_mode != "raw":
                mode, W, rows, base, alt = analyse_vectors(m, chunk_rows)
                if force_mode == "transpose" and mode == MODE_BITPACK:
                    mode = MODE_TRANSPOSE
                if force_mode == "bitpack" and mode != MODE_BITPACK:
                    raise PzstError(f"{m.name}: bitpack impossible, use auto")
            p = {"W": W, "rows": rows, "base": base, "alt": alt}
            if mode == MODE_T5ROW:
                p["alph"] = alph
            if mode == MODE_MIXED:
                p.update(cls=cls, palph=palph, plut=plut)
            ex = _write_member(w, m, mode, p, threads, chunk_rows)
            extra.update(ex)
            name_out = MODE_NAMES[mode]
            if mode == MODE_MIXED and force_mode == "t5col":
                name_out = "t5col"
            report.append({"name": m.name, "mode": name_out,
                           "size": m.size, "width": W, "rows": rows, **extra})
    return report


# -------------------------------------------------------------------- decoder
def iter_members(src_path, threads=-1):
    """Yield (name, mode, size, writer_fn) for each member of a .pzst file.
    writer_fn(fileobj) streams the reconstructed bytes and verifies the hash.
    writer_fn MUST be called for every member, in order."""
    fast.set_threads(threads if threads and threads > 0 else os.cpu_count())
    fin = open(src_path, "rb")
    head = fin.read(4)
    fin.seek(0)
    if head == ZSTD_MAGIC:
        r_ctx = zstd.ZstdDecompressor().stream_reader(fin, read_size=1 << 20,
                                                      read_across_frames=True)
    elif head == MAGIC[:4] and fin.read(5) == planes.MAGIC3:
        fin.seek(0)
        with fin:
            def wrap(emit):
                def run(out):
                    try:
                        emit(out)
                    except planes.PlanesError as e:
                        raise PzstError(str(e)) from None
                return run
            try:
                for name, mode, size, emit in planes.iter_members_v3(fin, threads):
                    yield name, mode, size, wrap(emit)
            except planes.PlanesError as e:
                raise PzstError(str(e)) from None
        return
    elif head == MAGIC[:4]:
        fin.seek(0)
        r_ctx = _Plain(fin)                       # packing-only container
    else:
        fin.close()
        raise PzstError(f"{src_path}: neither a zstd-wrapped nor a plain .pzst file")
    with fin, r_ctx as r:
        if _read_exact(r, len(MAGIC)) != MAGIC:
            raise PzstError(f"{src_path}: not a .pzst v2 file")
        (n,) = struct.unpack("<I", _need(r, 4))
        for _ in range(n):
            (nl,) = struct.unpack("<H", _need(r, 2))
            name = _need(r, nl).decode()
            mode, size = struct.unpack("<BQ", _need(r, 9))

            def emit(out, mode=mode, size=size, name=name):
                h = _hasher()
                if mode == MODE_T5S:
                    _read_t5_stream(r, size, out, h, name)
                elif mode == MODE_RAW:
                    left = size
                    while left:
                        b = _need(r, min(IO_BLOCK, left))
                        h.update(b)
                        out.write(b)
                        left -= len(b)
                else:
                    W, rows, R = struct.unpack("<IQI", _need(r, 16))
                    if rows * (W + 1) != size or W == 0 or R == 0:
                        raise PzstError(f"{name}: header size mismatch")
                    if mode == MODE_BITPACK:
                        base = np.frombuffer(_need(r, W), np.uint8).copy()
                        alt = np.frombuffer(_need(r, W), np.uint8).copy()
                    elif mode == MODE_T5ROW:
                        alph = np.frombuffer(_need(r, 3), np.uint8).copy()
                        if len(set(alph.tolist())) != 3 or 10 in alph:
                            raise PzstError(f"{name}: invalid t5row alphabet")
                    elif mode == MODE_MIXED:
                        cls = np.frombuffer(_need(r, W), np.uint8).copy()
                        palph = np.frombuffer(_need(r, 3 * W), np.uint8).reshape(W, 3).copy()
                        if cls.max(initial=0) > 2:
                            raise PzstError(f"{name}: invalid pin class")
                    elif mode != MODE_TRANSPOSE:
                        raise PzstError(f"{name}: unknown mode {mode}")
                    left = rows
                    while left:
                        c = min(R, left)
                        try:
                            if mode == MODE_TRANSPOSE:
                                a = fast.untranspose(_need(r, W * c), c, W)
                            elif mode == MODE_BITPACK:
                                a = fast.unpack(_need(r, W * ((c + 7) // 8)), c, W, base, alt)
                            elif mode == MODE_T5ROW:
                                a = ternary.row_unpack(_need(r, c * ((W + 4) // 5)), c, W, alph)
                            else:
                                a = ternary.mixed_unpack(_need(r, ternary.mixed_size(c, cls)),
                                                         c, W, cls, palph)
                        except ternary.TernaryError as e:
                            raise PzstError(f"{name}: {e}") from None
                        h.update(a)
                        out.write(a)
                        left -= c
                if h.digest() != _need(r, HASH_LEN):
                    raise PzstError(f"{name}: checksum mismatch - corrupted data")

            yield name, MODE_NAMES.get(mode, str(mode)), size, emit


def _read_t5_stream(r, size, out, h, name):
    done = 0
    while done < size:
        typ = _need(r, 1)[0]
        (n,) = struct.unpack("<I", _need(r, 4))
        if n == 0 or done + n > size:
            raise PzstError(f"{name}: bad t5 block length")
        if typ == BLK_RAW:
            b = _need(r, n)
        elif typ == BLK_T5:
            (m,) = struct.unpack("<I", _need(r, 4))
            alph = np.frombuffer(_need(r, 3), np.uint8)
            if m > 2 * n + 16 or len(set(alph.tolist())) != 3 or 10 in alph:
                raise PzstError(f"{name}: bad t5 block header")
            try:
                b = ternary.stream_decode(_need(r, m), alph, n)
            except ternary.TernaryError as e:
                raise PzstError(f"{name}: {e}") from None
        else:
            raise PzstError(f"{name}: unknown t5 block type {typ}")
        h.update(b)
        out.write(b)
        done += n


def decompress(src_path, dst, as_pat=False, threads=-1):
    """Restore a .pzst into directory `dst`, or into a .pat zip if as_pat."""
    if as_pat:
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, _, _, emit in iter_members(src_path, threads):
                with zf.open(name, "w", force_zip64=True) as out:
                    emit(out)
        return
    os.makedirs(dst, exist_ok=True)
    for name, _, _, emit in iter_members(src_path, threads):
        if os.path.basename(name) != name or name in ("", ".", ".."):
            raise PzstError(f"unsafe member name {name!r}")
        with open(os.path.join(dst, name), "wb") as out:
            emit(out)


def decompress_to_memory(src_path):
    """Return {name: bytes}. Convenient for small files / tests."""
    res = {}
    for name, _, _, emit in iter_members(src_path):
        buf = io.BytesIO()
        emit(buf)
        res[name] = buf.getvalue()
    return res
