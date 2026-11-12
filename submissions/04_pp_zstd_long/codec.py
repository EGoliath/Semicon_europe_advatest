"""pp + zstd --long : per-pin bit planes, one zstd frame with a window over the whole stream.

Vectors.vec is a grid (W pin symbols + '\\n' per vector). Every pin gets 0 bits
(constant), 1 bit plane (2 symbols) or 2 bit planes (3-4 symbols); code 0 is the
symbol of the first row. All planes are concatenated and compressed as ONE zstd
frame with long-distance matching and windowLog = log2(stream size) (max 31).
Other members (and a Vectors.vec that is not a clean grid) are one zstd frame each.

Member kinds in the PXT1 container (codec id 4):
    0  zstd frame of the member bytes
    1  u32 W, u64 rows, u32 table length, zstd-19(table = W*4 symbols + W plane counts),
       then the zstd frame of the plane stream
"""
import ctypes
import math
import os
import struct
import subprocess

import numpy as np

import patio

CODEC_ID = 4
DEFAULT_LEVEL = 19
HERE = os.path.dirname(os.path.abspath(__file__))
_SO, _SRC = os.path.join(HERE, "libpp.so"), os.path.join(HERE, "pp_kernels.c")
if not os.path.exists(_SO) or os.path.getmtime(_SO) < os.path.getmtime(_SRC):
    subprocess.check_call(["gcc", "-O3", "-march=native", "-fopenmp", "-shared", "-fPIC",
                           _SRC, "-lzstd", "-o", _SO])
L = ctypes.CDLL(_SO)
P, I64, I32, SZ = ctypes.c_void_p, ctypes.c_int64, ctypes.c_int, ctypes.c_size_t
for name, res, args in [
    ("xt_scan", I64, [P, I64, I32, P, I32]),
    ("xt_pack_planes", None, [P, I64, I32, P, P, P, P, I32]),
    ("xt_unpack_planes", None, [P, I64, I32, P, P, P, P, I32]),
    ("xt_zstd_bound", SZ, [SZ]),
    ("xt_zstd_compress", I64, [P, I64, P, I64, I32, I32, I32, I32]),
    ("xt_zstd_decompress", I64, [P, I64, P, I64]),
]:
    f = getattr(L, name)
    f.restype, f.argtypes = res, args


def ptr(a):
    return a.ctypes.data


def _wlog(n):
    return max(10, min(31, math.ceil(math.log2(max(n, 2)))))


def zstd(src, level, long, nth):
    n = len(src)
    dst = np.empty(L.xt_zstd_bound(n), np.uint8)
    r = L.xt_zstd_compress(ptr(src), n, ptr(dst), len(dst), level,
                           _wlog(n) if long else 0, 1 if long else 0, nth if nth > 1 else 0)
    if r < 0:
        raise RuntimeError("zstd compress failed")
    return dst[:r]


def unzstd(comp, n):
    comp = np.ascontiguousarray(comp)
    out = patio.alloc(n)
    if L.xt_zstd_decompress(ptr(comp), len(comp), ptr(out), n) != n:
        raise RuntimeError("zstd decompress failed")
    return out


class Planes:
    """Per-pin alphabet and plane offsets, from (sym, nb) and rows."""

    def __init__(self, W, rows, sym, nb):
        self.W, self.rows, self.sym, self.nb = W, rows, sym, nb
        self.nbytes = (rows + 7) // 8
        off0, off1, k = np.full(W, -1, np.int64), np.full(W, -1, np.int64), 0
        for p in range(W):
            if nb[p] >= 1:
                off0[p] = k * self.nbytes; k += 1
            if nb[p] == 2:
                off1[p] = k * self.nbytes; k += 1
        self.off0, self.off1, self.nplanes = off0, off1, k


def scan(buf, nth):
    """(Planes, lut) if buf is a clean grid with <= 4 symbols per pin, else None."""
    nl = np.flatnonzero(buf[:1 << 16] == 10)
    if not len(nl) or nl[0] == 0:
        return None
    W = int(nl[0])
    pres = np.zeros(W * 256, np.uint8)
    rows = L.xt_scan(ptr(buf), len(buf), W, ptr(pres), nth)
    if rows <= 0:
        return None
    pres = pres.reshape(W, 256)
    lut, sym, nb = np.zeros((W, 256), np.uint8), np.zeros((W, 4), np.uint8), np.zeros(W, np.int32)
    for p in range(W):
        syms = [int(c) for c in np.flatnonzero(pres[p])]
        if len(syms) > 4:
            return None
        first = int(buf[p])
        syms.remove(first)
        for k, c in enumerate([first] + syms):
            lut[p, c], sym[p, k] = k, c
        nb[p] = 0 if len(syms) == 0 else (1 if len(syms) == 1 else 2)
    return Planes(W, rows, sym, nb), lut


def compress(src, dst, level=19, threads=0):
    nth = threads or os.cpu_count()
    entries = []
    for name, buf in patio.read_members(src):
        dg = patio.digest(buf)
        s = scan(buf, nth) if len(buf) >= (1 << 20) else None
        if s is None:
            entries.append((name, len(buf), 0, [zstd(buf, level, len(buf) > (8 << 20), nth)], dg))
            continue
        g, lut = s
        stream = np.zeros(g.nplanes * g.nbytes, np.uint8)
        L.xt_pack_planes(ptr(buf), g.rows, g.W, ptr(lut), ptr(g.off0), ptr(g.off1), ptr(stream), nth)
        table = zstd(np.concatenate([g.sym.ravel(), g.nb.astype(np.uint8)]), 19, False, 1)
        head = struct.pack("<IQI", g.W, g.rows, len(table))
        entries.append((name, len(buf), 1, [head, table, zstd(stream, level, True, nth)], dg))
        del stream
    patio.write_container(dst, CODEC_ID, entries)


def iter_decompress(src, threads=0):
    nth = threads or os.cpu_count()
    for name, size, kind, payload, dg in patio.read_container(src, CODEC_ID):
        if kind == 0:
            out = unzstd(payload, size)
        elif kind == 1:
            W, rows, tl = struct.unpack_from("<IQI", payload, 0)
            t = unzstd(payload[16:16 + tl], W * 5)
            g = Planes(W, rows, t[:W * 4].reshape(W, 4).copy(), t[W * 4:].astype(np.int32))
            stream = unzstd(payload[16 + tl:], g.nplanes * g.nbytes)
            out = patio.alloc(size)
            L.xt_unpack_planes(ptr(stream), g.rows, g.W, ptr(g.sym), ptr(g.off0), ptr(g.off1), ptr(out), nth)
            del stream
        else:
            raise ValueError(f"unknown member kind {kind}")
        if patio.digest(out) != dg:
            raise ValueError(f"{name}: checksum mismatch")
        yield name, out
