"""extra_tests round 2: block-indexed split-stream zstd container (`bk`) + zstd sweep.
Standalone -- imports nothing from patzstd/, patamd/ or the round-1 xt files.

Configs
  raw:z<L>[L<wlog>]        plain zstd level L, optional --long=<wlog> (LDM)
                           e.g. raw:z9 (reference), raw:z3L27, raw:z19L27, raw:z22L31
  bk<R>:<L>[l][x]          container, R = Mi vectors per block (1, 4, 16 ...) or A = whole file,
                           L = zstd level, l = LDM with window = block stream, x = per-plane
                           transition (XOR along time) chosen by a zstd-1 trial, r = row repeat:
                           rows equal to the previous row are dropped and flagged in a bitmap,
                           g = each block's stored planes split into pin-group frames
                           (2 per inner thread) -> task-parallel compression/decompression
                           e.g. bk4:19l, bkA:9l, bk16:19lx, bk4:19lr
Container size = frames + block index + per-pin symbol table (zstd-19 compressed) + 24 B header.
Fallback (E8): files < 64 MB also try plain zstd at the same level and keep the smaller.
"""
import ctypes
import mmap
import os
import re
import subprocess

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
_SO, _SRC = os.path.join(HERE, "libxt2.so"), os.path.join(HERE, "xt2_kernels.c")
if not os.path.exists(_SO) or os.path.getmtime(_SO) < os.path.getmtime(_SRC):
    subprocess.check_call(["gcc", "-O3", "-march=native", "-fopenmp", "-shared", "-fPIC",
                           _SRC, "-lzstd", "-o", _SO])
L = ctypes.CDLL(_SO)
P, I64, I32, SZ = ctypes.c_void_p, ctypes.c_int64, ctypes.c_int, ctypes.c_size_t
PP = ctypes.POINTER(ctypes.c_void_p)
for name, res, args in [
    ("xt2_scan", I64, [P, I64, I32, P, I32]),
    ("xt2_row_hash", None, [P, I64, I32, P, I32]),
    ("xt2_eq_prev", I64, [P, I64, I32, I32]),
    ("xt2_encode", I64, [P, I64, I32, P, P, I64, I32, I32, I32, I32, I32, I32, PP, PP, ctypes.POINTER(I64), P]),
    ("xt2_decode", I32, [P, P, I64, I64, I32, P, P, P, I32]),
    ("xt2_free", None, [P]),
    ("xt2_set_params", None, [I32, I32, I32, I32, I32, I32]),
    ("xt2_zstd", I64, [P, I64, P, I64, I32, I32, I32, I32]),
    ("xt2_unzstd", I64, [P, I64, P, I64]),
    ("xt2_bound", SZ, [SZ]),
    ("xt2_equal", I32, [P, P, I64, I32]),
]:
    f = getattr(L, name)
    f.restype, f.argtypes = res, args

NTH = os.cpu_count()
FALLBACK_BELOW = 64 << 20


def set_threads(n):
    global NTH
    NTH = n


def ptr(a):
    return a.ctypes.data


def alloc(n):
    m = mmap.mmap(-1, max(n, 1))
    try:
        m.madvise(mmap.MADV_HUGEPAGE)
    except (AttributeError, OSError):
        pass
    return np.frombuffer(m, dtype=np.uint8, count=n)


def equal(a, b):
    return len(a) == len(b) and bool(L.xt2_equal(ptr(a), ptr(b), len(a), NTH))


def zstd(src, level, wlog=0, ldm=0):
    dst = np.empty(L.xt2_bound(len(src)), np.uint8)
    r = L.xt2_zstd(ptr(src), len(src), ptr(dst), len(dst), level, wlog, ldm, NTH if NTH > 1 else 0)
    if r < 0:
        raise RuntimeError("zstd failed")
    return dst[:r].copy()


def unzstd(comp, n):
    out = alloc(n)
    if L.xt2_unzstd(ptr(comp), len(comp), ptr(out), n) != n:
        raise RuntimeError("unzstd failed")
    return out


class Grid:
    def __init__(self, buf):
        self.ok = False
        nl = np.flatnonzero(buf[:1 << 16] == 10)
        if not len(nl) or nl[0] == 0:
            return
        W = int(nl[0])
        pres = np.zeros(W * 256, np.uint8)
        rows = L.xt2_scan(ptr(buf), len(buf), W, ptr(pres), NTH)
        if rows <= 0:
            return
        pres = pres.reshape(W, 256)
        lut, sym, nb = np.zeros((W, 256), np.uint8), np.zeros((W, 4), np.uint8), np.zeros(W, np.int32)
        for p in range(W):
            syms = [int(c) for c in np.flatnonzero(pres[p])]
            if len(syms) > 4:
                return
            first = int(buf[p])
            syms.remove(first)
            syms = [first] + syms
            for k, c in enumerate(syms):
                lut[p, c], sym[p, k] = k, c
            nb[p] = 0 if len(syms) == 1 else (1 if len(syms) == 2 else 2)
        self.ok, self.W, self.rows, self.lut, self.sym, self.nb = True, W, rows, lut, sym, nb


# -------------------------------------------------------------------- configs
RAW_RE = re.compile(r"^raw:z(\d+)(?:L(\d+))?$")
BK_RE = re.compile(r"^bk(\d+|A):(\d+)(l?)(x?)(r?)(g?)$")


def parse(cfg):
    m = RAW_RE.match(cfg)
    if m:
        return ("raw", int(m.group(1)), int(m.group(2) or 0))
    m = BK_RE.match(cfg)
    if m:
        R = 1 << 62 if m.group(1) == "A" else int(m.group(1)) << 20
        return ("bk", R, int(m.group(2)), bool(m.group(3)), bool(m.group(4)), bool(m.group(5)), bool(m.group(6)))
    raise ValueError(f"bad config {cfg!r}")


class Packed:
    pass


def compress(spec, buf, g):
    """Returns a Packed with .size (bytes a container file would hold) and .stat."""
    pk = Packed()
    pk.stat, pk.mode = None, "raw"
    if spec[0] == "raw":
        _, lvl, wlog = spec
        pk.comp = zstd(buf, lvl, wlog, 1 if wlog else 0)
        pk.size = len(pk.comp)
        return pk
    _, R, lvl, lng, ax, rr, gp = spec
    if g is None or not g.ok:
        pk.comp = zstd(buf, lvl)
        pk.size, pk.mode = len(pk.comp), "fallback"
        return pk
    dst, meta, ml = ctypes.c_void_p(), ctypes.c_void_p(), I64()
    stat = np.zeros(6, np.int64)
    tot = L.xt2_encode(ptr(buf), g.rows, g.W, ptr(g.lut), ptr(g.nb), R, lvl, int(lng), int(ax), int(rr), int(gp), NTH,
                       ctypes.byref(dst), ctypes.byref(meta), ctypes.byref(ml), ptr(stat))
    if tot < 0:
        raise RuntimeError("encode failed")
    pk.comp = np.frombuffer(ctypes.string_at(dst, tot), np.uint8)
    pk.meta = np.frombuffer(ctypes.string_at(meta, ml.value), np.uint8)
    L.xt2_free(dst); L.xt2_free(meta)
    table = np.concatenate([g.sym.ravel(), g.nb.astype(np.uint8), pk.meta])
    pk.size = tot + len(zstd(table, 19)) + 24
    pk.stat, pk.mode, pk.g = stat, "bk", g
    if len(buf) < FALLBACK_BELOW:
        alt = zstd(buf, lvl)
        if len(alt) < pk.size:
            pk.comp, pk.size, pk.mode = alt, len(alt), "fallback"
    return pk


def decompress(pk, n):
    if pk.mode != "bk":
        return unzstd(pk.comp, n)
    g = pk.g
    out = alloc(n)
    if L.xt2_decode(ptr(pk.comp), ptr(pk.meta), len(pk.meta), g.rows, g.W, ptr(g.nb), ptr(g.sym),
                    ptr(out), NTH):
        raise RuntimeError("decode failed")
    return out
