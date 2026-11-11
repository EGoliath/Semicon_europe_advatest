"""Black-box round-trip bench. Usage: bench.py <workroot> <csv> <methods,comma> <file>...
Each run: compress in a fresh dir (input is a hardlink, TEMP points to an empty dir), check for side files,
delete the input link, move ONLY the compressed file to a second fresh dir, rename the original away,
decompress in a new process there, restore the original name, compare SHA-256."""
import ctypes, ctypes.wintypes as wt, csv, hashlib, os, shutil, subprocess, sys, time

BIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")
TRIES = os.path.abspath(os.path.join(BIN, "tries.exe"))
GZIP = r"C:\Program Files\Git\usr\bin\gzip.exe"
XZ = r"C:\Program Files\Git\mingw64\bin\xz.exe"
PY = sys.executable
ZST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zst.py")

class PMC(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD)] + [(n, ctypes.c_size_t) for n in (
        "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
        "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
psapi = ctypes.WinDLL("psapi")

def run(cmd, cwd, env, stdout=None):
    t = time.perf_counter()
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=stdout or subprocess.DEVNULL, stderr=subprocess.PIPE)
    _, err = p.communicate()
    dt = time.perf_counter() - t
    m = PMC(); m.cb = ctypes.sizeof(PMC)
    psapi.GetProcessMemoryInfo(wt.HANDLE(int(p._handle)), ctypes.byref(m), m.cb)  # handle still open after exit
    # private commit only: tries.exe memory-maps its input, and mapped pages would inflate the working set
    return p.returncode, dt, m.PeakPagefileUsage / 2**20, err.decode(errors="replace").strip()

def retry(fn, *a):  # Windows: AV/indexer may hold a just-closed file briefly
    for i in range(50):
        try: return fn(*a)
        except PermissionError:
            if i == 49: raise
            time.sleep(0.2)

def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(1 << 22): h.update(b)
    return h.hexdigest()

def cmds(method, i, o):
    """returns (compress_cmd, stdout_file_or_None), (decompress_cmd, stdout_file_or_None)"""
    kind, lvl = method.rstrip("0123456789"), method[len(method.rstrip("0123456789")):]
    if kind in ("pack", "packlong", "tp"):
        name = {"pack": "pack", "packlong": "pack-long", "tp": "tp"}[kind]
        return ([TRIES, "c", name, lvl, i, o], None), ([TRIES, "d", o, "restored.dat"], None)
    if kind == "zstd":
        return ([PY, "-I", ZST, "c", lvl, i, o], None), ([PY, "-I", ZST, "d", o, "restored.dat"], None)
    if kind == "gzip":
        return ([GZIP, f"-{lvl}", "-n", "-c", i], o), ([GZIP, "-d", "-c", o], "restored.dat")
    if kind == "xz":
        return ([XZ, f"-{lvl}", "-T1", "-c", i], o), ([XZ, "-d", "-c", o], "restored.dat")
    raise SystemExit("bad method " + method)

def one(root, f, method, ref):
    size = os.path.getsize(f)
    tag = f"{os.path.basename(f)}__{method}"
    cdir, ddir, tmp = (os.path.join(root, x, tag) for x in ("c", "d", "tmp"))
    for d in (cdir, ddir, tmp):
        shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    env = dict(os.environ, TEMP=tmp, TMP=tmp)
    inp = os.path.join(cdir, "input.dat"); os.link(f, inp)
    (cc, cout), (dc, dout) = cmds(method, "input.dat", "out.compr")
    bin_before = sorted(os.listdir(BIN))
    with (open(os.path.join(cdir, cout), "wb") if cout else open(os.devnull, "wb")) as so:
        crc, ct, cmem, cerr = run(cc, cdir, env, so if cout else None)
    side = sorted(set(os.listdir(cdir)) - {"input.dat", "out.compr"}) + [f"TEMP:{x}" for x in os.listdir(tmp)]
    retry(os.remove, inp)
    comp = os.path.join(cdir, "out.compr")
    csize = os.path.getsize(comp) if os.path.exists(comp) else -1
    if csize >= 0: retry(shutil.move, comp, os.path.join(ddir, "out.compr"))
    hidden = f + ".hidden_during_decompress"
    retry(os.rename, f, hidden)
    try:
        with (open(os.path.join(ddir, dout), "wb") if dout else open(os.devnull, "wb")) as so:
            drc, dtm, dmem, derr = run(dc, ddir, env, so if dout else None)
    finally:
        retry(os.rename, hidden, f)
    side += [f"TEMP:{x}" for x in os.listdir(tmp)] + [f"BIN:{x}" for x in set(os.listdir(BIN)) - set(bin_before)]
    rest = os.path.join(ddir, "restored.dat")
    ok = os.path.exists(rest) and os.path.getsize(rest) == size and sha(rest) == ref
    for d in (cdir, ddir, tmp): shutil.rmtree(d, ignore_errors=True)
    mb = size / 1e6
    return dict(file=os.path.basename(f), size=size, method=method, csize=csize,
                ratio=round(size / csize, 3) if csize > 0 else "", c_s=round(ct, 3), d_s=round(dtm, 3),
                c_MBps=round(mb / ct, 1), d_MBps=round(mb / dtm, 1), c_peakMB=round(cmem, 1), d_peakMB=round(dmem, 1),
                c_rc=crc, d_rc=drc, sha_ok=ok, side_files=";".join(side), err=(cerr + " | " + derr)[:300])

def main():
    root, out, methods, files = sys.argv[1], sys.argv[2], sys.argv[3].split(","), sys.argv[4:]
    new = not os.path.exists(out)
    with open(out, "a", newline="") as fo:
        w = None
        for f in files:
            ref = sha(f)
            for m in methods:
                r = one(root, os.path.abspath(f), m, ref)
                if w is None:
                    w = csv.DictWriter(fo, list(r)); new and w.writeheader()
                w.writerow(r); fo.flush()
                print(f"{r['file']:32} {m:7} {r['size']:>12} -> {r['csize']:>11}  x{r['ratio']:<8} "
                      f"c {r['c_MBps']:>7} MB/s d {r['d_MBps']:>7} MB/s  mem {r['c_peakMB']}/{r['d_peakMB']} MB  "
                      f"ok={r['sha_ok']} rc={r['c_rc']}/{r['d_rc']} {r['side_files']} {r['err'][:120] if not r['sha_ok'] else ''}",
                      flush=True)

main()
