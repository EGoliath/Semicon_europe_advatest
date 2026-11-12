"""Tests for patamd (AMD single-core / multi-core copies + new back ends).

    .venv/bin/python -m unittest tests.test_amd -v
"""
import os
import random
import subprocess
import sys
import tempfile
import unittest

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patamd  # noqa: E402
from patamd import cpu, fast  # noqa: E402
from patzstd import decompress_to_memory as orig_decompress  # noqa: E402
from test_codec import make_pat, rand_vec, rb, wb  # noqa: E402

PROFILES = ("st", "mt")
V4_MODES = ("planes", "planesxz", "pcm", "planesbwt")
V2_MODES = ("auto", "mixed", "best")


def structured_vec(rows, seed=0):
    """Pins with repeats, a clock, duplicates, an inverted copy, constants, H/L/X."""
    rnd = random.Random(seed)
    block = [rnd.choice("01") for _ in range(97)]
    a = "".join(block[i % 97] if rnd.random() > 0.02 else rnd.choice("01") for i in range(rows))
    clk = "".join("01"[(i // 3) % 2] for i in range(rows))
    noise = "".join(rnd.choice("01") for _ in range(rows))
    inv = a.translate(str.maketrans("01", "LH"))
    hlx = "".join(rnd.choice("HLX") for _ in range(rows))
    cols = [a, clk, noise, a, inv, "0" * rows, "X" * rows, hlx, noise]
    return "".join("".join(c[r] for c in cols) + "\n" for r in range(rows)).encode()


class AmdRoundTrip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def rt(self, vec, mode, prof, level, **kw):
        src = os.path.join(self.d, "in.pat")
        orig = make_pat(src, vec, **kw)
        dst = os.path.join(self.d, "x.pzst")
        patamd.compress(src, dst, level=level, force_mode=f"amd_{mode}_{prof}")
        self.assertEqual(patamd.decompress_to_memory(dst, profile=prof), orig, (mode, prof, level))
        return dst, orig

    def test_all_modes_both_profiles(self):
        vec = structured_vec(4000)
        for prof in PROFILES:
            for mode in V4_MODES + V2_MODES:
                lvl = 2 if mode == "pcm" else 1 if mode == "planesbwt" else 6 if mode == "planesxz" else 9
                self.rt(vec, mode, prof, lvl)

    def test_shapes(self):
        for rows in (0, 1, 7, 9, 63, 1001):
            v = rand_vec(rows, 5, ["01", "LH", "0", "X", "01"], seed=rows) if rows else b""
            for mode in ("planes", "pcm"):
                self.rt(v, mode, "mt", 2 if mode == "pcm" else 3)

    def test_pcm_levels_and_segments(self):
        vec = structured_vec(3000, seed=3)
        src = os.path.join(self.d, "in.pat")
        orig = make_pat(src, vec)
        for lvl in (1, 2, 3):
            for seg in (8, 1000, 1 << 24):
                dst = os.path.join(self.d, "x.pzst")
                patamd.compress(src, dst, level=lvl, force_mode="amd_pcm_mt", seg_rows=seg)
                self.assertEqual(patamd.decompress_to_memory(dst), orig)

    def test_st_and_mt_write_identical_v4_files(self):
        vec = structured_vec(5000, seed=5)
        for mode, lvl in (("planes", 19), ("planesxz", 6), ("pcm", 2)):
            a, _ = self.rt(vec, mode, "st", lvl)
            ba = rb(a)
            b, _ = self.rt(vec, mode, "mt", lvl)
            self.assertEqual(ba, rb(b), mode)

    def test_v2_copies_readable_by_original_decoder(self):
        vec = structured_vec(3000, seed=7)
        for mode in V2_MODES:
            for prof in PROFILES:
                dst, orig = self.rt(vec, mode, prof, 9)
                self.assertEqual(rb(dst)[:4], b"\x28\xb5\x2f\xfd")
                self.assertEqual(orig_decompress(dst), orig)

    def test_reads_original_v3_files(self):
        from patzstd import compress as orig_compress
        src = os.path.join(self.d, "in.pat")
        orig = make_pat(src, structured_vec(2000))
        dst = os.path.join(self.d, "v3.pzst")
        orig_compress(src, dst, level=3, force_mode="planes")
        self.assertEqual(patamd.decompress_to_memory(dst), orig)

    def test_non_grid_member_falls_back(self):
        self.rt(b"ragged\nlines here\n", "pcm", "mt", 2)
        self.rt(b"no newline at end", "planesxz", "st", 6)

    def test_corruption_detected(self):
        dst, _ = self.rt(structured_vec(2000, seed=9), "pcm", "mt", 2)
        data = rb(dst)
        rnd = random.Random(1)
        bad = os.path.join(self.d, "bad.pzst")
        for pos in sorted({rnd.randrange(len(data)) for _ in range(60)} | {0, 5, len(data) - 1}):
            b = bytearray(data)
            b[pos] ^= 0x41
            wb(bad, bytes(b))
            with self.assertRaises(Exception, msg=f"flip at {pos}"):
                patamd.decompress_to_memory(bad)

    def test_bad_mode_names(self):
        for name in ("amd_planes", "amd_foo_mt", "planes_mt", "amd_planes_xx"):
            with self.assertRaises(patamd.PzstError):
                patamd.parse_mode(name)


class AmdKernels(unittest.TestCase):
    def test_pcm_roundtrip_and_lag(self):
        rnd = np.random.default_rng(0)
        base = rnd.integers(0, 2, 200, dtype=np.uint8)
        bits = np.tile(base, 400)[:80000]
        bits[rnd.integers(0, len(bits), 500)] ^= 1
        s = np.packbits(bits).tobytes()
        lag = fast.pick_lag(s)
        for lv in (1, 2, 3):
            for L in (0, lag, 64):
                c = fast.pcm_encode(s, len(s), 1, [L], lv)
                self.assertLess(len(c), len(s) // 3)
                self.assertEqual(fast.pcm_decode(c, len(s), 1, [L], lv), s)

    def test_pcm_edge_streams(self):
        for s in (b"\x00", b"\xff" * 3, bytes(range(256)) * 9, os.urandom(5000)):
            c = fast.pcm_encode(s, len(s), 1, [0], 2)
            self.assertEqual(fast.pcm_decode(c, len(s), 1, [0], 2), s)

    def test_isa_variants_identical(self):
        """generic / avx2 (/ avx512 when the CPU has it) produce the same bytes."""
        code = ("import sys; sys.path.insert(0, %r); import numpy as np; from patamd import fast; "
                "r=np.random.default_rng(1); buf=(r.integers(0,2,(999,33))+48).astype(np.uint8); "
                "g=np.concatenate([buf,np.full((999,1),10,np.uint8)],1).tobytes(); "
                "p=fast.pack(g,999,33,np.full(33,48,np.uint8)); "
                "c=fast.pcm_encode(p.tobytes()[:126],126,1,[0],2); "
                "import hashlib; print(fast.variant(), hashlib.sha256(p.tobytes()+c).hexdigest())") % ROOT
        outs = {}
        have = cpu.isa()
        for isa in ("generic", "avx2", "avx512"):
            if {"generic": 0, "avx2": 1, "avx512": 2}[isa] > {"generic": 0, "avx2": 1, "avx512": 2}[have]:
                continue
            env = dict(os.environ, PATAMD_ISA=isa)
            r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)
            v, h = r.stdout.split()
            self.assertEqual(v, isa)
            outs[isa] = h
        self.assertGreaterEqual(len(outs), 2)
        self.assertEqual(len(set(outs.values())), 1, outs)

    def test_topology(self):
        t = cpu.topo()
        self.assertEqual(sorted(t["order"]), cpu.allowed_cpus())
        self.assertGreaterEqual(t["physical"], 1)
        p = cpu.Profile("st")
        self.assertEqual((p.workers, p.zstd_threads, len(p.cpus)), (1, 0, 1))
        self.assertEqual(cpu.Profile("mt", 3).workers, 3)


if __name__ == "__main__":
    unittest.main()
