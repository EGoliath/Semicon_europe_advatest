"""bk : block-indexed split-stream zstd container (round 2, default = bkA:19lg).

Vectors.vec is cut into blocks of R vectors (default: one block for the whole file).
Per block, every pin's bit plane is classified ZERO / ONES / COPY(q) / NOT(q) / STORED,
so constant, duplicated and complemented pins cost nothing. The stored planes are split
into pin-group frames (independent zstd frames, LDM, window = frame), compressed and
decompressed in parallel (OpenMP blocks x frames); decoding writes every row straight to
its final offset. Files < 64 MB also try plain zstd and keep the smaller.

Member kinds in the PXT1 container (codec id 5):
    0  zstd frame of the member bytes
    1  u32 W, u64 rows, u64 meta length, u32 table length,
       zstd-19(table = W*4 symbols + W plane counts + block index), then the frames
"""
import ctypes
import os
import struct
import subprocess

import numpy as np

import patio

CODEC_ID = 5
DEFAULT_LEVEL = 19
FALLBACK_BELOW = 64 << 20
EXTRA_ARGS = [
    ("--block", dict(default="A", help="vectors per block in Mi (1, 4, 16 ...) or A = whole file (default A)")),
    ("--no-ldm", dict(action="store_true", help="disable long-distance matching inside the frames")),
]

HERE = os.path.dirname(os.path.abspath(__file__))
_SO, _SRC = os.path.join(HERE, "libbk.so"), os.path.join(HERE, "bk_kernels.c")
if not os.path.exists(_SO) or os.path.getmtime(_SO) < os.path.getmtime(_SRC):
    subprocess.check_call(["gcc", "-O3", "-march=native", "-fopenmp", "-shared", "-fPIC",
                           _SRC, "-lzstd", "-o", _SO])
L = ctypes.CDLL(_SO)
P, I64, I32, SZ = ctypes.c_void_p, ctypes.c_int64, ctypes.c_int, ctypes.c_size_t
PP = ctypes.POINTER(ctypes.c_void_p)
for name, res, args in [
    ("xt2_scan", I64, [P, I64, I32, P, I32]),
    ("xt2_encode", I64, [P, I64, I32, P, P, I64, I32, I32, I32, I32, I32, I32, PP, PP, ctypes.POINTER(I64), P]),
    ("xt2_decode", I32, [P, P, I64, I64, I32, P, P, P, I32]),
    ("xt2_free", None, [P]),
    ("xt2_zstd", I64, [P, I64, P, I64, I32, I32, I32, I32]),
    ("xt2_unzstd", I64, [P, I64, P, I64]),
    ("xt2_bound", SZ, [SZ]),
]:
    f = getattr(L, name)
    f.restype, f.argtypes = res, args


def ptr(a):
    return a.ctypes.data


def zstd(src, level, nth):
    dst = np.empty(L.xt2_bound(len(src)), np.uint8)
    r = L.xt2_zstd(ptr(src), len(src), ptr(dst), len(dst), level, 0, 0, nth if nth > 1 else 0)
    if r < 0:
        raise RuntimeError("zstd compress failed")
    return dst[:r]


def unzstd(comp, n):
    comp = np.ascontiguousarray(comp)
    out = patio.alloc(n)
    if L.xt2_unzstd(ptr(comp), len(comp), ptr(out), n) != n:
        raise RuntimeError("zstd decompress failed")
    return out


def scan(buf, nth):
    nl = np.flatnonzero(buf[:1 << 16] == 10)
    if not len(nl) or nl[0] == 0:
        return None
    W = int(nl[0])
    pres = np.zeros(W * 256, np.uint8)
    rows = L.xt2_scan(ptr(buf), len(buf), W, ptr(pres), nth)
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
    return W, rows, lut, sym, nb


def _encode_grid(buf, s, level, R, ldm, nth):
    W, rows, lut, sym, nb = s
    dst, meta, ml = ctypes.c_void_p(), ctypes.c_void_p(), I64()
    stat = np.zeros(6, np.int64)
    tot = L.xt2_encode(ptr(buf), rows, W, ptr(lut), ptr(nb), R, level, int(ldm), 0, 0, 1, nth,
                       ctypes.byref(dst), ctypes.byref(meta), ctypes.byref(ml), ptr(stat))
    if tot < 0:
        raise RuntimeError("bk encode failed")
    frames = ctypes.string_at(dst, tot)
    meta_b = np.frombuffer(ctypes.string_at(meta, ml.value), np.uint8)
    L.xt2_free(dst); L.xt2_free(meta)
    table = zstd(np.concatenate([sym.ravel(), nb.astype(np.uint8), meta_b]), 19, 1)
    head = struct.pack("<IQQI", W, rows, len(meta_b), len(table))
    return [head, table, frames]


def compress(src, dst, level=DEFAULT_LEVEL, threads=0, block="A", no_ldm=False):
    nth = threads or os.cpu_count()
    R = 1 << 62 if str(block).upper() == "A" else int(block) << 20
    entries = []
    for name, buf in patio.read_members(src):
        dg = patio.digest(buf)
        s = scan(buf, nth) if len(buf) >= (1 << 20) else None
        if s is not None:
            parts = _encode_grid(buf, s, level, R, not no_ldm, nth)
            if len(buf) < FALLBACK_BELOW:
                alt = zstd(buf, level, nth)
                if len(alt) < sum(len(p) for p in parts):
                    s, parts = None, None
                    entries.append((name, len(buf), 0, [alt], dg))
            if parts is not None:
                entries.append((name, len(buf), 1, parts, dg))
        else:
            entries.append((name, len(buf), 0, [zstd(buf, level, nth)], dg))
    patio.write_container(dst, CODEC_ID, entries)


def iter_decompress(src, threads=0):
    nth = threads or os.cpu_count()
    for name, size, kind, payload, dg in patio.read_container(src, CODEC_ID):
        if kind == 0:
            out = unzstd(payload, size)
        elif kind == 1:
            W, rows, ml, tl = struct.unpack_from("<IQQI", payload, 0)
            t = unzstd(payload[24:24 + tl], W * 5 + ml)
            sym = np.ascontiguousarray(t[:W * 4])
            nb = t[W * 4:W * 5].astype(np.int32)
            meta = np.ascontiguousarray(t[W * 5:])
            frames = np.ascontiguousarray(payload[24 + tl:])
            out = patio.alloc(size)
            if L.xt2_decode(ptr(frames), ptr(meta), ml, rows, W, ptr(nb), ptr(sym), ptr(out), nth):
                raise RuntimeError(f"{name}: bk decode failed")
        else:
            raise ValueError(f"unknown member kind {kind}")
        if patio.digest(out) != dg:
            raise ValueError(f"{name}: checksum mismatch")
        yield name, out
