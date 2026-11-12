"""Shared I/O for the PXT container (used by the zstd baseline, pp_zstd_long and bk_container packages).

Input: a .pat / .zip archive or a folder with the extracted members
(Program.sprg, Vectors.vec, Comments.cmt).

Container (.pxt), little endian:
    b"PXT1"  u8 codec id   u32 member count
    per member:
        u16 name length, name (utf-8)
        u64 original size
        u8  kind            (codec specific, 0 = plain zstd frame of the member)
        u64 payload length, payload
        16 B xxh3-128 of the original member bytes (checked on decompression)
"""
import mmap
import os
import struct
import zipfile

import numpy as np
import xxhash

MAGIC = b"PXT1"
ORDER = ["Program.sprg", "Vectors.vec", "Comments.cmt"]


def alloc(n):
    """Zeroed buffer on transparent huge pages."""
    m = mmap.mmap(-1, max(n, 1))
    try:
        m.madvise(mmap.MADV_HUGEPAGE)
    except (AttributeError, OSError):
        pass
    return np.frombuffer(m, dtype=np.uint8, count=n)


def _read_into(f, out):
    mv, got = memoryview(out), 0
    while got < len(out):
        k = f.readinto(mv[got:])
        if not k:
            raise IOError("short read")
        got += k
    return out


def read_members(path):
    """[(name, np.uint8 array)] in a stable order."""
    out = []
    if os.path.isdir(path):
        names = [n for n in os.listdir(path) if os.path.isfile(os.path.join(path, n))]
        names.sort(key=lambda n: (ORDER.index(n) if n in ORDER else 99, n))
        for n in names:
            p = os.path.join(path, n)
            with open(p, "rb") as f:
                out.append((n, _read_into(f, alloc(os.path.getsize(p)))))
        return out
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            for i in zf.infolist():
                if not i.is_dir():
                    with zf.open(i) as f:
                        out.append((i.filename, _read_into(f, alloc(i.file_size))))
        return out
    raise ValueError(f"{path}: not a folder or .pat/.zip archive")


def digest(buf):
    return xxhash.xxh3_128_digest(memoryview(buf))


def write_container(dst, codec_id, entries):
    """entries: [(name, size, kind, [payload parts], digest)]"""
    with open(dst, "wb") as f:
        f.write(MAGIC + struct.pack("<BI", codec_id, len(entries)))
        for name, size, kind, parts, dg in entries:
            nb = name.encode()
            plen = sum(len(p) for p in parts)
            f.write(struct.pack("<H", len(nb)) + nb + struct.pack("<QBQ", size, kind, plen))
            for p in parts:
                f.write(memoryview(p))
            f.write(dg)


def read_container(src, codec_id):
    """Yields (name, size, kind, payload np.uint8 view, digest)."""
    with open(src, "rb") as f:
        data = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    buf = np.frombuffer(data, np.uint8)
    if bytes(data[:4]) != MAGIC:
        raise ValueError(f"{src}: not a PXT1 container")
    cid, nm = struct.unpack_from("<BI", data, 4)
    if cid != codec_id:
        raise ValueError(f"{src}: codec id {cid}, this decoder handles {codec_id}")
    o = 9
    for _ in range(nm):
        (ln,) = struct.unpack_from("<H", data, o); o += 2
        name = bytes(data[o:o + ln]).decode(); o += ln
        size, kind, plen = struct.unpack_from("<QBQ", data, o); o += 17
        payload = buf[o:o + plen]; o += plen
        dg = bytes(data[o:o + 16]); o += 16
        if os.path.basename(name) != name or name in ("", ".", ".."):
            raise ValueError(f"unsafe member name {name!r}")
        yield name, size, kind, payload, dg


def write_members(dst, members, as_pat=False):
    """members: iterable of (name, buffer). Folder dst/, or a .pat zip if as_pat."""
    if as_pat:
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, b in members:
                with zf.open(name, "w", force_zip64=True) as out:
                    out.write(memoryview(b))
        return
    os.makedirs(dst, exist_ok=True)
    for name, b in members:
        with open(os.path.join(dst, name), "wb") as out:
            out.write(memoryview(b))


def stem_of(path):
    base = os.path.basename(path.rstrip("/"))
    for ext in (".pat", ".zip", ".pxt"):
        if base.endswith(ext):
            return base[:-len(ext)]
    return base
