"""ctypes bridge to kernels.c (built on first use). Falls back to numpy if
the C library cannot be built; set PATZSTD_NO_C=1 to force the fallback."""
import ctypes
import os
import subprocess

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "kernels.c")
LIB = os.path.join(HERE, "libpatk.so")

_lib = None


def _build():
    cmd = ["gcc", "-O3", "-march=native", "-fopenmp", "-shared", "-fPIC", SRC, "-o", LIB]
    subprocess.run(cmd, check=True, capture_output=True)


def lib():
    global _lib
    if _lib is not None or os.environ.get("PATZSTD_NO_C"):
        return _lib
    try:
        if not os.path.exists(LIB) or os.path.getmtime(LIB) < os.path.getmtime(SRC):
            _build()
        L = ctypes.CDLL(LIB)
    except Exception:
        return None
    P, S, I = ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int
    L.pk_analyse.argtypes = [P, S, I, P]
    L.pk_analyse.restype = I
    L.pk_pack.argtypes = [P, S, I, P, P]
    L.pk_unpack.argtypes = [P, S, I, P, P, P]
    L.pk_transpose.argtypes = [P, S, I, P]
    L.pk_untranspose.argtypes = [P, S, I, P]
    L.pk_set_threads.argtypes = [I]
    _lib = L
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
