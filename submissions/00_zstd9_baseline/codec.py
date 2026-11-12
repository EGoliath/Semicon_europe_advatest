"""Baseline: plain zstd -9 on every member (default zstd parameters, no transform).

This is the reference all other packages are compared against.
Member kinds in the PXT1 container (codec id 0):
    0  zstd frame of the member bytes
"""
import os

import zstandard

import patio

CODEC_ID = 0
DEFAULT_LEVEL = 9


def compress(src, dst, level=DEFAULT_LEVEL, threads=0):
    nth = threads or os.cpu_count()
    entries = []
    for name, buf in patio.read_members(src):
        c = zstandard.ZstdCompressor(level=level, threads=nth if nth > 1 else 0).compress(memoryview(buf))
        entries.append((name, len(buf), 0, [c], patio.digest(buf)))
    patio.write_container(dst, CODEC_ID, entries)


def iter_decompress(src, threads=0):
    d = zstandard.ZstdDecompressor()
    for name, size, kind, payload, dg in patio.read_container(src, CODEC_ID):
        if kind != 0:
            raise ValueError(f"unknown member kind {kind}")
        out = d.decompress(memoryview(payload), max_output_size=size)
        if len(out) != size or patio.digest(out) != dg:
            raise ValueError(f"{name}: checksum mismatch")
        yield name, out
