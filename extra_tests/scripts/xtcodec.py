"""extra_tests codec family `xt` -- standalone (imports nothing from patzstd/ or patamd/).

A config is  LAYOUT:BACKEND

LAYOUT (how Vectors.vec is rearranged before the back-end compressor)
  raw   bytes as they are (baseline)
  tr8   per-pin byte streams (transpose, 1 byte/symbol, newlines dropped)
  pp    per-pin bit planes: 1 bit/vector for 2-symbol pins, 2 planes for 3-4
        symbols, 0 for constant pins (bit packing + transpose)
  ppd   pp + XOR along time inside every plane (bit transitions)
  rx    row-major bit rows (same bits as pp), row[n] XOR row[n-1]

BACKEND
  zstd9 / zstd19        one frame, zstd multi-threaded compression
  zstd9L / zstd19L      one frame, --long=31 (LDM, window up to 2 GiB)
  zstd9R / zstd3R       RAP: independent 16 MiB frames, OpenMP (de)compression
  bz3                   bzip3 (BWT), 64 MiB blocks, multi-threaded
  br9                   brotli q9 lgwin 24, 64 MiB blocks in parallel
  lz4hc / lz4           LZ4 HC level 12 / LZ4 fast, 16 MiB blocks in parallel
  dfl9                  deflate (zlib) level 9, 16 MiB blocks in parallel

Every decode allocates its output with mmap + MADV_HUGEPAGE (preallocated
once, filled in place by the kernels / threads).
"""
import ctypes
import math
import mmap
import os
import subprocess
import sys
import zlib
from concurrent.futures import ThreadPoolExecutor

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "_pydeps"))
import brotli  # noqa: E402
import bz3  # noqa: E402
import lz4.block  # noqa: E402

NTH = os.cpu_count()
MiB = 1 << 20

# ------------------------------------------------------------------ C library
_SO = os.path.join(HERE, "libxt.so")
_SRC = os.path.join(HERE, "xt_kernels.c")
if not os.path.exists(_SO) or os.path.getmtime(_SO) < os.path.getmtime(_SRC):
    subprocess.check_call(["gcc", "-O3", "-march=native", "-fopenmp", "-shared", "-fPIC",
                           _SRC, "-lzstd", "-o", _SO])
L = ctypes.CDLL(_SO)
P, I64, I32, SZ = ctypes.c_void_p, ctypes.c_int64, ctypes.c_int, ctypes.c_size_t
for name, res, args in [
    ("xt_scan", I64, [P, I64, I32, P, I32]),
    ("xt_pack_planes", None, [P, I64, I32, P, P, P, P, I32]),
    ("xt_unpack_planes", None, [P, I64, I32, P, P, P, P, I32]),
    ("xt_trans_fwd", None, [P, I64, I64, I32]),
    ("xt_trans_inv", None, [P, I64, I64, I32]),
    ("xt_transpose", None, [P, I64, I32, P, I32]),
    ("xt_untranspose", None, [P, I64, I32, P, I32]),
    ("xt_pack_rows", None, [P, I64, I32, P, P, I32, I32, P, P, I32]),
    ("xt_unpack_rows", None, [P, I64, I32, P, P, I32, I32, P, I32]),
    ("xt_zstd_bound", SZ, [SZ]),
    ("xt_zstd_compress", I64, [P, I64, P, I64, I32, I32, I32, I32]),
    ("xt_zstd_decompress", I64, [P, I64, P, I64]),
    ("xt_zstd_rap_compress", I64, [P, I64, I64, I32, I32, P, P, I32]),
    ("xt_zstd_rap_decompress", I64, [P, P, I64, I64, I64, P, I32]),
    ("xt_equal", I32, [P, P, I64]),
]:
    f = getattr(L, name)
    f.restype, f.argtypes = res, args


def ptr(a):
    return a.ctypes.data


def as_np(b):
    return b if isinstance(b, np.ndarray) else np.frombuffer(b, dtype=np.uint8)


def alloc(n):
    """Preallocated output on transparent huge pages."""
    m = mmap.mmap(-1, max(n, 1))
    try:
        m.madvise(mmap.MADV_HUGEPAGE)
    except (AttributeError, OSError):
        pass
    return np.frombuffer(m, dtype=np.uint8, count=n)


def equal(a, b):
    return len(a) == len(b) and bool(L.xt_equal(ptr(as_np(a)), ptr(as_np(b)), len(a)))


# --------------------------------------------------------------------- layout
class Grid:
    """Scan of one Vectors.vec: width, rows and per-pin alphabets."""

    def __init__(self, buf):
        self.ok = False
        nl = np.flatnonzero(buf[:1 << 16] == 10)
        if not len(nl):
            return
        W = int(nl[0])
        pres = np.zeros(W * 256, np.uint8) if W else None
        rows = L.xt_scan(ptr(buf), len(buf), W, ptr(pres), NTH) if W else -1
        if rows <= 0:
            return
        pres = pres.reshape(W, 256)
        lut = np.zeros((W, 256), np.uint8)
        sym = np.zeros((W, 4), np.uint8)
        nb = np.zeros(W, np.int32)
        for p in range(W):
            syms = [int(c) for c in np.flatnonzero(pres[p])]
            if len(syms) > 4:
                return
            first = int(buf[p])
            syms.remove(first)
            syms = [first] + syms                     # code 0 = first-row symbol
            for k, c in enumerate(syms):
                lut[p, c] = k
                sym[p, k] = c
            nb[p] = 0 if len(syms) == 1 else (1 if len(syms) == 2 else 2)
        self.ok, self.W, self.rows = True, W, rows
        self.lut, self.sym, self.nb = lut, sym, nb
        self.nbytes = (rows + 7) // 8
        off0, off1, k = np.full(W, -1, np.int64), np.full(W, -1, np.int64), 0
        for p in range(W):
            if nb[p] >= 1:
                off0[p] = k * self.nbytes; k += 1
            if nb[p] == 2:
                off1[p] = k * self.nbytes; k += 1
        self.off0, self.off1, self.nplanes = off0, off1, k
        self.B = max(1, (int(nb.sum()) + 7) // 8)    # bytes per packed row

    def meta_bytes(self):
        """Exact size of the header a container would store for this layout."""
        return 4 + 4 + 8 + self.W * 5               # magic, W, rows, sym+nb table


def make_layout(name, buf, g):
    if name == "raw":
        return buf
    if name == "tr8":
        out = np.empty(g.rows * g.W, np.uint8)
        L.xt_transpose(ptr(buf), g.rows, g.W, ptr(out), NTH)
        return out
    if name in ("pp", "ppd"):
        out = np.zeros(g.nplanes * g.nbytes, np.uint8)
        L.xt_pack_planes(ptr(buf), g.rows, g.W, ptr(g.lut), ptr(g.off0), ptr(g.off1), ptr(out), NTH)
        if name == "ppd":
            L.xt_trans_fwd(ptr(out), g.nplanes, g.nbytes, NTH)
        return out
    if name == "rx":
        out = np.empty(g.rows * g.B, np.uint8)
        tmp = np.empty(g.rows * g.B, np.uint8)
        L.xt_pack_rows(ptr(buf), g.rows, g.W, ptr(g.lut), ptr(g.nb), g.B, 1, ptr(tmp), ptr(out), NTH)
        return out
    raise ValueError(name)


def stream_len(name, n, g):
    return {"raw": n, "tr8": g.rows * g.W if g else 0, "pp": g.nplanes * g.nbytes if g else 0,
            "ppd": g.nplanes * g.nbytes if g else 0, "rx": g.rows * g.B if g else 0}[name]


def undo_layout(name, s, g, n):
    """s = decoded stream (np, writable for ppd). Returns the reconstructed file."""
    if name == "raw":
        return s
    out = alloc(n)
    if name == "tr8":
        L.xt_untranspose(ptr(s), g.rows, g.W, ptr(out), NTH)
    elif name in ("pp", "ppd"):
        if name == "ppd":
            L.xt_trans_inv(ptr(s), g.nplanes, g.nbytes, NTH)
        L.xt_unpack_planes(ptr(s), g.rows, g.W, ptr(g.sym), ptr(g.off0), ptr(g.off1), ptr(out), NTH)
    elif name == "rx":
        L.xt_unpack_rows(ptr(s), g.rows, g.W, ptr(g.sym), ptr(g.nb), g.B, 1, ptr(out), NTH)
    return out


# -------------------------------------------------------------------- backend
def _blocks(n, bs):
    return [(o, min(bs, n - o)) for o in range(0, n, bs)] or [(0, 0)]


class Blob:
    """Compressed payload: list of frames + the index bytes a container needs."""

    def __init__(self, frames, index_bytes, **kw):
        self.frames, self.index_bytes, self.kw = frames, index_bytes, kw

    @property
    def size(self):
        return sum(len(f) for f in self.frames) + self.index_bytes


def _wlog(n):
    return max(10, min(31, math.ceil(math.log2(max(n, 2)))))


def zstd_compress(s, level, long=False):
    n = len(s)
    dst = np.empty(L.xt_zstd_bound(n), np.uint8)
    r = L.xt_zstd_compress(ptr(s), n, ptr(dst), len(dst), level,
                           _wlog(n) if long else 0, 1 if long else 0, NTH)
    if r < 0:
        raise RuntimeError("zstd compress failed")
    return Blob([dst[:r]], 0)


def zstd_decompress(b, n):
    out = alloc(n)
    r = L.xt_zstd_decompress(ptr(b.frames[0]), len(b.frames[0]), ptr(out), n)
    if r != n:
        raise RuntimeError("zstd decompress failed")
    return out


def rap_compress(s, level, bs=16 * MiB):
    n = len(s)
    nblk = max(1, -(-n // bs))
    dst = np.empty(nblk * L.xt_zstd_bound(bs), np.uint8)
    csz = np.zeros(nblk, np.int64)
    r = L.xt_zstd_rap_compress(ptr(s), n, bs, level, 0, ptr(dst), ptr(csz), NTH)
    if r < 0:
        raise RuntimeError("rap compress failed")
    return Blob([dst[:r]], 8 * nblk + 8, csz=csz, bs=bs)


def rap_decompress(b, n):
    out = alloc(n)
    csz = b.kw["csz"]
    r = L.xt_zstd_rap_decompress(ptr(b.frames[0]), ptr(csz), len(csz), b.kw["bs"], n, ptr(out), NTH)
    if r != n:
        raise RuntimeError("rap decompress failed")
    return out


def pool_compress(s, fn, bs):
    mv = memoryview(s)
    blocks = _blocks(len(s), bs)
    with ThreadPoolExecutor(NTH) as ex:
        frames = list(ex.map(lambda ol: fn(mv[ol[0]:ol[0] + ol[1]]), blocks))
    return Blob(frames, 8 * len(frames) + 8, bs=bs)


def pool_decompress(b, n, fn):
    out = alloc(n)
    bs = b.kw["bs"]

    def one(k):
        d = fn(b.frames[k], min(bs, n - k * bs))
        out[k * bs:k * bs + len(d)] = np.frombuffer(d, np.uint8)
        return len(d)

    with ThreadPoolExecutor(NTH) as ex:
        tot = sum(ex.map(one, range(len(b.frames))))
    if tot != n:
        raise RuntimeError("block decompress size mismatch")
    return out


def bz3_compress(s, bs=64 * MiB):
    bs = max(65 * 1024, min(bs, len(s) + 1024, 511 * MiB))
    th = max(1, min(NTH, -(-len(s) // bs)))
    return Blob([bz3.compress(memoryview(s), block_size=bs, num_threads=th)], 0, th=th)


def bz3_decompress(b, n):
    d = bz3.decompress(bytes(b.frames[0]), num_threads=b.kw["th"])
    out = alloc(n)
    out[:] = np.frombuffer(d, np.uint8)
    return out


BACKENDS = {
    "zstd9":   (lambda s: zstd_compress(s, 9),                zstd_decompress),
    "zstd19":  (lambda s: zstd_compress(s, 19),               zstd_decompress),
    "zstd9L":  (lambda s: zstd_compress(s, 9, long=True),     zstd_decompress),
    "zstd19L": (lambda s: zstd_compress(s, 19, long=True),    zstd_decompress),
    "zstd9R":  (lambda s: rap_compress(s, 9),                 rap_decompress),
    "zstd3R":  (lambda s: rap_compress(s, 3),                 rap_decompress),
    "bz3":     (bz3_compress,                                 bz3_decompress),
    "br9":     (lambda s: pool_compress(s, lambda m: brotli.compress(bytes(m), quality=9, lgwin=24), 64 * MiB),
                lambda b, n: pool_decompress(b, n, lambda f, k: brotli.decompress(f))),
    "lz4hc":   (lambda s: pool_compress(s, lambda m: lz4.block.compress(m, mode="high_compression",
                                                                        compression=12, store_size=False), 16 * MiB),
                lambda b, n: pool_decompress(b, n, lambda f, k: lz4.block.decompress(f, uncompressed_size=k))),
    "lz4":     (lambda s: pool_compress(s, lambda m: lz4.block.compress(m, mode="default", store_size=False), 16 * MiB),
                lambda b, n: pool_decompress(b, n, lambda f, k: lz4.block.decompress(f, uncompressed_size=k))),
    "dfl9":    (lambda s: pool_compress(s, lambda m: zlib.compress(m, 9), 16 * MiB),
                lambda b, n: pool_decompress(b, n, lambda f, k: zlib.decompress(f))),
}

LAYOUTS = ("raw", "tr8", "pp", "ppd", "rx")


def parse(cfg):
    lay, be = cfg.split(":")
    if lay not in LAYOUTS or be not in BACKENDS:
        raise ValueError(f"bad config {cfg!r}")
    return lay, be
