"""ctypes bridge to the patamd C code (copy of patzstd/fast.py, extended).

One shared library per ISA variant is built on first use from kernels_amd.c
(transform kernels, OpenMP) + cm.c (pcm context-mixing coder):

    libpatamd_generic.so   -O3 -march=x86-64-v2
    libpatamd_avx2.so      -O3 -march=x86-64-v3 -mtune=znver3
    libpatamd_avx512.so    -O3 -march=znver4 -mprefer-vector-width=512

cpu.isa() picks the best variant the CPU supports (PATAMD_ISA caps it).
The transforms produce identical bytes on every variant (tests check it);
pcm is integer-only, so its output is identical too.
Falls back to numpy for the transforms if no C library can be built
(PATAMD_NO_C=1 forces that); pcm has no fallback.
"""
import ctypes
import os
import subprocess

import numpy as np

from . import cpu

HERE = os.path.dirname(os.path.abspath(__file__))
SRCS = [os.path.join(HERE, "kernels_amd.c"), os.path.join(HERE, "cm.c")]
FLAGS = {
    "generic": ["-march=x86-64-v2"],
    "avx2": ["-march=x86-64-v3", "-mtune=znver3"],
    "avx512": ["-march=znver4", "-mprefer-vector-width=512"],
}

_lib = None
_variant = None


def lib_path(variant):
    return os.path.join(HERE, f"libpatamd_{variant}.so")


def _build(variant):
    out = lib_path(variant)
    cmd = ["gcc", "-O3", *FLAGS[variant], "-fopenmp", "-shared", "-fPIC", *SRCS, "-o", out + ".tmp"]
    subprocess.run(cmd, check=True, capture_output=True)
    os.replace(out + ".tmp", out)


def variant():
    lib()
    return _variant


def lib():
    global _lib, _variant
    if _lib is not None or os.environ.get("PATAMD_NO_C"):
        return _lib
    v = cpu.isa()
    path = lib_path(v)
    try:
        if not os.path.exists(path) or os.path.getmtime(path) < max(os.path.getmtime(s) for s in SRCS):
            _build(v)
        L = ctypes.CDLL(path)
    except Exception:
        return None
    P, S, I, LL = ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int64
    L.pk_analyse.argtypes = [P, S, I, P]
    L.pk_analyse.restype = I
    L.pk_pack.argtypes = [P, S, I, P, P]
    L.pk_unpack.argtypes = [P, S, I, P, P, P]
    L.pk_transpose.argtypes = [P, S, I, P]
    L.pk_untranspose.argtypes = [P, S, I, P]
    L.pk_set_threads.argtypes = [I]
    L.pcm_encode.argtypes = [P, S, I, P, P, P, S, I]
    L.pcm_encode.restype = LL
    L.pcm_decode.argtypes = [P, S, S, I, P, P, P, I]
    L.pcm_decode.restype = LL
    _lib, _variant = L, v
    return L


def set_threads(n):
    L = lib()
    if L and n and n > 0:
        L.pk_set_threads(n)


def _p(a):
    return a.ctypes.data_as(ctypes.c_void_p)


def _u8(buf):
    return np.frombuffer(buf, np.uint8)


# Every function takes/returns contiguous uint8 numpy arrays / bytes-like.
def analyse(buf, rows, W, pres):
    """OR presence map (W x 256 uint8) of chunk into pres; False if not a grid."""
    a = _u8(buf)
    L = lib()
    if L:
        return L.pk_analyse(_p(a), rows, W, _p(pres)) == 0
    g = a.reshape(rows, W + 1)
    if not (g[:, W] == 10).all() or (g[:, :W] == 10).any():
        return False
    for c in range(W):
        pres[c, np.unique(g[:, c])] = 1
    return True


def pack(buf, rows, W, base):
    nb = (rows + 7) // 8
    out = np.empty(W * nb, np.uint8)
    L = lib()
    if L:
        L.pk_pack(_p(_u8(buf)), rows, W, _p(base), _p(out))
        return out
    body = _u8(buf).reshape(rows, W + 1)[:, :W]
    return np.packbits((body != base).T, axis=1).reshape(-1)


def unpack(packed, rows, W, base, alt):
    out = np.empty(rows * (W + 1), np.uint8)
    L = lib()
    if L:
        L.pk_unpack(_p(_u8(packed)), rows, W, _p(base), _p(alt), _p(out))
        return out
    nb = (rows + 7) // 8
    bits = np.unpackbits(_u8(packed).reshape(W, nb), axis=1, count=rows).T.astype(bool)
    o = out.reshape(rows, W + 1)
    o[:, W] = 10
    o[:, :W] = np.where(bits, alt, base)
    return out


def transpose(buf, rows, W):
    out = np.empty(rows * W, np.uint8)
    L = lib()
    if L:
        L.pk_transpose(_p(_u8(buf)), rows, W, _p(out))
        return out
    return np.ascontiguousarray(_u8(buf).reshape(rows, W + 1)[:, :W].T).reshape(-1)


def untranspose(data, rows, W):
    out = np.empty(rows * (W + 1), np.uint8)
    L = lib()
    if L:
        L.pk_untranspose(_p(_u8(data)), rows, W, _p(out))
        return out
    o = out.reshape(rows, W + 1)
    o[:, W] = 10
    o[:, :W] = _u8(data).reshape(W, rows).T
    return out


# ------------------------------------------------------------- pcm coder
def pcm_encode(streams_bytes, nb, n, lags, level):
    """n streams of nb bytes (concatenated) -> compressed bytes. One model per call;
    patamd calls it with n = 1 (one frame per pin stream). Releases the GIL."""
    L = lib()
    if L is None:
        raise RuntimeError("pcm needs the C library (gcc)")
    a = _u8(streams_bytes)
    lag = np.ascontiguousarray(lags, np.int32)
    ref = np.full(n, -1, np.int32)
    cap = len(a) + len(a) // 16 + 4096
    out = np.empty(cap, np.uint8)
    r = L.pcm_encode(_p(a), nb, n, _p(lag), _p(ref), _p(out), cap, level)
    if r < 0:
        raise RuntimeError("pcm output overflow")
    return out[:r].tobytes()


def pcm_decode(comp, nb, n, lags, level):
    L = lib()
    if L is None:
        raise RuntimeError("pcm needs the C library (gcc)")
    a = _u8(comp)
    lag = np.ascontiguousarray(lags, np.int32)
    ref = np.full(n, -1, np.int32)
    out = np.empty(nb * n, np.uint8)
    L.pcm_decode(_p(a), len(a), nb, n, _p(lag), _p(ref), _p(out), level)
    return out.tobytes()


_LAGS = (8, 16, 24, 32, 40, 48, 64, 80, 96, 128, 160, 192, 256, 384, 512, 768, 1024)


def pick_lag(stream, sample_bytes=1 << 17):
    """Per-pin lag for the pcm lag model: the candidate L (multiple of 8, so the
    bit phase is preserved) whose x[t] == x[t-L] agreement is highest on a sample.
    0 if no candidate beats the plain 'same as previous bit' agreement."""
    s = _u8(stream)
    if len(s) > sample_bytes:
        s = s[(len(s) - sample_bytes) // 2:][:sample_bytes]
    x = np.unpackbits(s)
    if len(x) < 4096:
        return 0
    base = np.mean(x[1:] == x[:-1])
    best, bl = base, 0
    for L in _LAGS:
        a = np.mean(x[L:] == x[:-L])
        if a > best + 1e-4:
            best, bl = a, L
    return bl
