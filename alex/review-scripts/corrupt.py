"""Damage a pack9 file and check that tries.exe d fails loudly (rc!=0) and never exits 0 with wrong output.
Usage: corrupt.py <workdir> <file>..."""
import hashlib, os, subprocess, sys
TRIES = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "tries.exe"))
wd = sys.argv[1]; os.makedirs(wd, exist_ok=True)
H = lambda b: hashlib.sha256(b).hexdigest()
for f in sys.argv[2:]:
    orig = open(f, "rb").read()
    good = os.path.join(wd, "good.compr")
    subprocess.run([TRIES, "c", "pack", "9", f, good], check=True, capture_output=True)
    g = open(good, "rb").read()
    n = len(g)
    flip = lambda b, i: b[:i] + bytes([b[i] ^ 0x01]) + b[i + 1:]
    cases = {"empty": b"", "magic_only": g[:4], "trunc_1": g[:-1], "trunc_half": g[:n // 2],
             "flip_hdr5": flip(g, 5), "flip_mid": flip(g, n // 2), "flip_last": flip(g, n - 1),
             "append_junk": g + b"junk", "wrong_magic": b"VPK9" + g[4:]}
    for name, data in cases.items():
        p, o = os.path.join(wd, "bad.compr"), os.path.join(wd, "out.dat")
        open(p, "wb").write(data)
        if os.path.exists(o): os.remove(o)
        r = subprocess.run([TRIES, "d", p, o], capture_output=True, timeout=600)
        out = open(o, "rb").read() if os.path.exists(o) else None
        same = out is not None and H(out) == H(orig)
        verdict = "SILENT-CORRUPTION" if r.returncode == 0 and not same else ("ok-error" if r.returncode else "ok-recovered")
        print(f"{os.path.basename(f):24} {name:12} rc={r.returncode:<11} out={'none' if out is None else len(out):>10} "
              f"{verdict}  {r.stderr.decode(errors='replace').strip()[:90]}")
r = subprocess.run([TRIES, "d", os.path.join(wd, "does_not_exist"), os.path.join(wd, "x")], capture_output=True)
print("missing input rc", r.returncode, r.stderr.decode(errors="replace").strip()[:90])
