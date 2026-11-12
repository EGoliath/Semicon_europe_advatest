"""Ternary packing: 5 symbols from a 3-symbol alphabet -> 1 byte (3^5 = 243).

    C = d0 + 3*d1 + 9*d2 + 27*d3 + 81*d4        (d0 = first symbol)

Three layouts (see docs/FORMAT.md):
  * stream  (t5)    : generic byte stream, in-band tokens 243..248 for newline,
                      partial groups and literal bytes; per block alphabet.
  * row     (t5row) : fixed-width vector grid, one alphabet for the file,
                      ceil(W/5) bytes per vector, newline implicit.
  * mixed / t5col   : pin-major per-pin radix (constant / binary / ternary).

Each layout has a C kernel (kernels.c) and a pure Python / numpy reference
implementation (`*_ref`) used by the tests and as the un-optimised baseline.
"""
import ctypes

import numpy as np

from . import fast

POW3 = np.array([1, 3, 9, 27, 81], np.uint32)
TOK_NL, TOK_PART, TOK_LIT = 243, 244, 248          # 244..247 = partial k=1..4
CLS_CONST, CLS_BIN, CLS_TER = 0, 1, 2
ERRORS = {-1: "invalid token", -2: "output overflow", -3: "truncated token",
          -4: "partial group value out of range", -5: "non-canonical literal"}


class TernaryError(ValueError):
    pass


_P, _S, _I, _LL = ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_longlong
_ready = False


def _lib():
    global _ready
    L = fast.lib()
    if L and not _ready:
        L.t5s_encode.argtypes = [_P, _S, _P, _P]
        L.t5s_encode.restype = _S
        L.t5s_decode.argtypes = [_P, _S, _P, _P, _S, _I]
        L.t5s_decode.restype = _LL
        L.t5r_pack.argtypes = [_P, _S, _I, _P, _P]
        L.t5r_pack.restype = _I
        L.t5r_unpack.argtypes = [_P, _S, _I, _P, _P, _I]
        L.t5r_unpack.restype = _I
        L.mx_pack.argtypes = [_P, _S, _I, _P, _P, _P]
        L.mx_pack.restype = _I
        L.mx_unpack.argtypes = [_P, _S, _I, _P, _P, _P, _I]
        L.mx_unpack.restype = _I
        L.mx_payload.argtypes = [_S, _I, _P]
        L.mx_payload.restype = _S
        L.t5_hist.argtypes = [_P, _S, _P]
        L.t5_init()
        _ready = True
    return L


def _p(a):
    return a.ctypes.data_as(ctypes.c_void_p)


def _u8(b):
    return np.frombuffer(b, np.uint8)


# ------------------------------------------------------------------ alphabets
def _hist(block):
    L = _lib()
    src = _u8(block)
    if not L:
        return np.bincount(src, minlength=256).astype(np.int64)
    out = np.empty(256, np.uint64)
    L.t5_hist(_p(src), len(src), _p(out))
    return out.astype(np.int64)


def stream_alphabet(block):
    """3 most frequent bytes of the block other than '\\n' (padded with unused
    byte values so that the alphabet always has 3 distinct entries)."""
    cnt = _hist(block)
    cnt[10] = -1
    order = np.argsort(-cnt, kind="stable")
    alph = [int(b) for b in order[:3] if cnt[b] > 0]
    for b in range(256):                    # fillers
        if len(alph) == 3:
            break
        if b != 10 and b not in alph:
            alph.append(b)
    return np.array(alph, np.uint8)


def lut_from_alphabet(alph):
    lut = np.full(256, 255, np.uint8)
    for d, s in enumerate(alph):
        lut[s] = d
    return lut


def pin_classes(pres, force_ternary=False):
    """Per pin: class + 3-byte alphabet from the presence map (W x 256)."""
    W = pres.shape[0]
    cls = np.zeros(W, np.uint8)
    alph = np.zeros((W, 3), np.uint8)
    lut = np.full((W, 256), 255, np.uint8)
    for c in range(W):
        syms = [int(s) for s in np.flatnonzero(pres[c])]
        if len(syms) > 3 or 10 in syms:
            raise TernaryError(f"pin {c} has {len(syms)} symbols")
        k = len(syms)
        cls[c] = CLS_TER if force_ternary else (CLS_CONST if k <= 1 else CLS_BIN if k == 2 else CLS_TER)
        fill = [b for b in range(32, 127) if b not in syms]
        full = (syms + fill)[:3]
        alph[c] = full
        for d, s in enumerate(syms):
            lut[c, s] = d
    return cls, alph, lut


# ===================================================================== stream
def stream_encode_ref(block, alph):
    """Pure Python reference encoder."""
    lut = lut_from_alphabet(alph)
    out = bytearray()
    acc = k = 0
    for b in bytes(block):
        d = lut[b]
        if d < 3:
            acc += int(d) * int(POW3[k])
            k += 1
            if k == 5:
                out.append(acc)
                acc = k = 0
            continue
        if k:
            out += bytes((243 + k, acc))
            acc = k = 0
        out += bytes((TOK_NL,)) if b == 10 else bytes((TOK_LIT, b))
    if k:
        out += bytes((243 + k, acc))
    return bytes(out)


def stream_decode_ref(enc, alph, orig_len):
    out = bytearray()
    i, n = 0, len(enc)
    a = [int(x) for x in alph]
    while i < n:
        c = enc[i]
        i += 1
        if c < 243:
            for _ in range(5):
                out.append(a[c % 3])
                c //= 3
        elif c == TOK_NL:
            out.append(10)
        elif c <= 247:
            k = c - 243
            if i >= n:
                raise TernaryError("truncated token")
            v = enc[i]
            i += 1
            if v >= 3 ** k:
                raise TernaryError("partial group value out of range")
            for _ in range(k):
                out.append(a[v % 3])
                v //= 3
        elif c == TOK_LIT:
            if i >= n:
                raise TernaryError("truncated token")
            b = enc[i]
            i += 1
            if b == 10 or b in a:
                raise TernaryError("non-canonical literal")
            out.append(b)
        else:
            raise TernaryError("invalid token")
        if len(out) > orig_len:
            raise TernaryError("output overflow")
    if len(out) != orig_len:
        raise TernaryError("decoded length mismatch")
    return bytes(out)


def stream_encode(block, alph):
    L = _lib()
    if not L:
        return stream_encode_ref(block, alph)
    src = _u8(block)
    lut = lut_from_alphabet(alph)
    out = np.empty(2 * len(src) + 16, np.uint8)
    n = L.t5s_encode(_p(src), len(src), _p(lut), _p(out))
    return out[:n]


def stream_decode(enc, alph, orig_len, use_lut=True):
    L = _lib()
    if not L:
        return stream_decode_ref(bytes(enc), alph, orig_len)
    src = _u8(enc)
    out = np.empty(max(orig_len, 1), np.uint8)
    a = np.ascontiguousarray(alph, np.uint8)
    n = L.t5s_decode(_p(src), len(src), _p(a), _p(out), orig_len, int(use_lut))
    if n < 0:
        raise TernaryError(ERRORS.get(n, f"error {n}"))
    if n != orig_len:
        raise TernaryError("decoded length mismatch")
    return out[:orig_len]


# ======================================================================== row
def row_pack_ref(buf, rows, W, alph):
    lut = lut_from_alphabet(alph)
    g = _u8(buf).reshape(rows, W + 1)[:, :W]
    d = lut[g]
    if (d > 2).any():
        raise TernaryError("symbol outside file alphabet")
    G = (W + 4) // 5
    pad = np.zeros((rows, G * 5), np.uint32)
    pad[:, :W] = d
    return (pad.reshape(rows, G, 5) @ POW3).astype(np.uint8).reshape(-1)


def row_unpack_ref(enc, rows, W, alph):
    G = (W + 4) // 5
    v = _u8(enc).reshape(rows, G).astype(np.uint32)
    lim = np.full(G, 243, np.uint32)
    if W % 5:
        lim[-1] = 3 ** (W % 5)
    if (v >= lim).any():
        raise TernaryError("group value out of range")
    digits = (v[:, :, None] // POW3) % 3                       # rows x G x 5
    out = np.empty((rows, W + 1), np.uint8)
    out[:, :W] = np.asarray(alph, np.uint8)[digits.reshape(rows, G * 5)[:, :W]]
    out[:, W] = 10
    return out.reshape(-1)


def row_pack(buf, rows, W, alph):
    L = _lib()
    if not L:
        return row_pack_ref(buf, rows, W, alph)
    out = np.empty(rows * ((W + 4) // 5), np.uint8)
    lut = lut_from_alphabet(alph)
    if L.t5r_pack(_p(_u8(buf)), rows, W, _p(lut), _p(out)):
        raise TernaryError("symbol outside file alphabet")
    return out


def row_unpack(enc, rows, W, alph, use_lut=True):
    L = _lib()
    if not L:
        return row_unpack_ref(enc, rows, W, alph)
    out = np.empty(rows * (W + 1), np.uint8)
    a = np.ascontiguousarray(alph, np.uint8)
    if L.t5r_unpack(_p(_u8(enc)), rows, W, _p(a), _p(out), int(use_lut)):
        raise TernaryError("group value out of range")
    return out


# ====================================================================== mixed
def mixed_size(rows, cls):
    nb, ng = (rows + 7) // 8, (rows + 4) // 5
    return int(sum(nb if c == CLS_BIN else ng if c == CLS_TER else 0 for c in cls))


def mixed_pack_ref(buf, rows, W, cls, lut):
    g = _u8(buf).reshape(rows, W + 1)[:, :W]
    d = lut[np.arange(W), g]                                   # rows x W digits
    parts = []
    for c in range(W):
        col = d[:, c]
        if cls[c] == CLS_CONST:
            if (col != 0).any():
                raise TernaryError("constant pin changes")
        elif cls[c] == CLS_BIN:
            if (col > 1).any():
                raise TernaryError("binary pin has 3rd symbol")
            parts.append(np.packbits(col.astype(bool)))
        else:
            if (col > 2).any():
                raise TernaryError("pin symbol outside alphabet")
            ng = (rows + 4) // 5
            pad = np.zeros(ng * 5, np.uint32)
            pad[:rows] = col
            parts.append((pad.reshape(ng, 5) @ POW3).astype(np.uint8))
    return np.concatenate(parts) if parts else np.empty(0, np.uint8)


def mixed_unpack_ref(enc, rows, W, cls, alph):
    out = np.empty((rows, W + 1), np.uint8)
    out[:, W] = 10
    e = _u8(enc)
    o = 0
    nb, ng = (rows + 7) // 8, (rows + 4) // 5
    for c in range(W):
        if cls[c] == CLS_CONST:
            out[:, c] = alph[c][0]
        elif cls[c] == CLS_BIN:
            bits = np.unpackbits(e[o:o + nb], count=rows)
            out[:, c] = alph[c][bits]
            o += nb
        else:
            v = e[o:o + ng].astype(np.uint32)
            lim = np.full(ng, 243, np.uint32)
            if rows % 5:
                lim[-1] = 3 ** (rows % 5)
            if (v >= lim).any():
                raise TernaryError("group value out of range")
            dig = ((v[:, None] // POW3) % 3).reshape(-1)[:rows]
            out[:, c] = alph[c][dig]
            o += ng
    return out.reshape(-1)


def mixed_pack(buf, rows, W, cls, lut):
    L = _lib()
    if not L:
        return mixed_pack_ref(buf, rows, W, cls, lut)
    cls = np.ascontiguousarray(cls, np.uint8)
    out = np.empty(max(L.mx_payload(rows, W, _p(cls)), 1), np.uint8)
    if L.mx_pack(_p(_u8(buf)), rows, W, _p(cls), _p(np.ascontiguousarray(lut)), _p(out)):
        raise TernaryError("pin symbol outside its alphabet")
    return out[:mixed_size(rows, cls)]


def mixed_unpack(enc, rows, W, cls, alph, use_lut=True):
    L = _lib()
    if not L:
        return mixed_unpack_ref(enc, rows, W, cls, alph)
    cls = np.ascontiguousarray(cls, np.uint8)
    out = np.empty(rows * (W + 1), np.uint8)
    if L.mx_unpack(_p(_u8(enc)), rows, W, _p(cls), _p(np.ascontiguousarray(alph, np.uint8)),
                   _p(out), int(use_lut)):
        raise TernaryError("group value out of range")
    return out
