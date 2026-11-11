"""Generate synthetic test files: edge cases, random, and vec-like ATE rows. Usage: gen.py <outdir> [big_bytes]"""
import os, sys

out = sys.argv[1]
big = int(sys.argv[2]) if len(sys.argv) > 2 else 0
os.makedirs(out, exist_ok=True)
P = lambda n: os.path.join(out, n)

def tbl(thresh, hi, lo):  # byte < thresh -> hi, else lo
    return bytes(hi if b < thresh else lo for b in range(256))

T_SCAN, T_NEAR, T_LH = tbl(179, 0x31, 0x30), tbl(1, 0x31, 0x30), tbl(154, ord('H'), ord('L'))
W = 96  # pins

def vec_block(rows, eol=b"\n"):
    lw = W + len(eol)
    buf = bytearray(rows * lw)
    for c in range(W):
        if c < 30:   t = T_SCAN
        elif c < 40: buf[c::lw] = b"X" * rows; continue
        elif c < 90: t = T_NEAR
        else:        t = T_LH
        buf[c::lw] = os.urandom(rows).translate(t)
    for i, ch in enumerate(eol):
        buf[W + i::lw] = bytes([ch]) * rows
    return bytes(buf)

def write_vec(name, total, eol=b"\n"):
    left = total // (W + len(eol))
    with open(P(name), "wb") as f:
        while left:
            n = min(50000, left)
            f.write(vec_block(n, eol)); left -= n

if big:  # big-only mode: gen.py <outdir> <bytes>
    write_vec(f"synvec_{big // 10**6}M.vec", big); sys.exit()
open(P("empty.bin"), "wb").close()
open(P("one_byte.bin"), "wb").write(b"A")
open(P("one_newline.bin"), "wb").write(b"\n")
open(P("zeros_10M.bin"), "wb").write(bytes(10_000_000))
open(P("repeat_text_10M.txt"), "wb").write((b"the quick brown fox jumps over the lazy dog 0123456789\n" * 200000)[:10_000_000])
open(P("repeat_vecrow_10M.vec"), "wb").write(b"0101XXXXLHLH10\n" * 666667)
open(P("random_10M.bin"), "wb").write(os.urandom(10_000_000))
open(P("novec_noeol.vec"), "wb").write(b"0101")
write_vec("synvec_100M.vec", 100_000_000)
write_vec("synvec_crlf_20M.vec", 20_000_000, b"\r\n")
# ragged: valid vec rows with one short row and one long row in the middle, no final newline
v = vec_block(20000)
lw = W + 1
mid = 10000 * lw
open(P("synvec_ragged.vec"), "wb").write(v[:mid] + b"0101\n" + b"1" * 300 + b"\n" + v[mid:-1])
# mixed alphabet rows: random printable bytes in fixed width rows
open(P("fixedwidth_random_ascii.vec"), "wb").write(
    b"".join(bytes(33 + b % 94 for b in os.urandom(W)) + b"\n" for _ in range(20000)))
if big:
    write_vec("synvec_big.vec", big)
print("ok")
