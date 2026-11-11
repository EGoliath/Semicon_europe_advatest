"""Tests for the `planes` / `planesxz` modes (container v3, patzstd/planes.py).

    .venv/bin/python -m unittest tests.test_planes -v
"""
import os
import random
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patzstd import compress, decompress_to_memory, PzstError  # noqa: E402
from patzstd.codec import iter_members  # noqa: E402
from test_codec import make_pat, rand_vec, rb, wb  # noqa: E402


def vec_from_cols(cols):
    """cols: list of equal-length strings, one per pin -> Vectors.vec bytes."""
    rows = len(cols[0])
    return "".join("".join(c[r] for c in cols) + "\n" for r in range(rows)).encode()


class Planes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def roundtrip(self, vec, mode="planes", level=3, seg_rows=None, expect="planes", **kw):
        src = os.path.join(self.d, "in.pat")
        orig = make_pat(src, vec, **kw)
        dst = os.path.join(self.d, "x.pzst")
        rep = compress(src, dst, level=level, force_mode=mode, seg_rows=seg_rows)
        self.assertEqual(rb(dst)[:5], b"PZST\x03")
        self.assertEqual(decompress_to_memory(dst), orig)
        vm = next(r for r in rep if r["name"] == "Vectors.vec")
        self.assertEqual(vm["mode"], expect)
        return vm, dst

    # ---------------------------------------------------------------- shapes
    def test_random_binary_pins(self):
        self.roundtrip(rand_vec(5000, 17, ["01"] * 17))

    def test_rows_not_multiple_of_8_and_many_segments(self):
        for rows in (1, 7, 9, 63, 1001):
            for seg in (8, 16, 1 << 24):
                self.roundtrip(rand_vec(rows, 5, ["01", "LH", "0", "X", "01"], seed=rows), seg_rows=seg)

    def test_empty_vectors_and_empty_members(self):
        self.roundtrip(b"", expect="zraw")
        self.roundtrip(rand_vec(10, 3, ["01"] * 3), comments=b"")

    def test_levels_and_packing_only(self):
        v = rand_vec(3000, 9, seed=4)
        for lvl in (None, 1, 9, 19):
            self.roundtrip(v, level=lvl)
        for lvl in (None, 0, 6, 9):
            self.roundtrip(v, mode="planesxz", level=lvl)

    def test_non_grid_falls_back_to_zraw(self):
        self.roundtrip(b"0101\n01\n", expect="zraw")             # ragged
        self.roundtrip(b"0101\r\n0110\r\n")       # CRLF: '\r' is just a constant pin
        self.roundtrip(b"0101\n0110", expect="zraw")             # no final newline
        self.roundtrip(rand_vec(50, 4, ["0123"] * 4), expect="zraw")   # 4 symbols on a pin

    def test_large_member_zraw_multi_frame(self):
        big = bytes(random.Random(1).getrandbits(8) for _ in range(70_000))
        self.roundtrip(big * 600, expect="zraw")               # 42 MB > one 32 MiB frame

    # ------------------------------------------------------- pin aliasing
    def test_duplicate_inverse_and_mirror_pins(self):
        rnd = random.Random(7)
        a = "".join(rnd.choice("01") for _ in range(4000))
        inv = a.translate(str.maketrans("01", "10"))
        lh = a.translate(str.maketrans("01", "LH"))
        b = "".join(rnd.choice("01") for _ in range(4000))
        cols = [a, b, a, inv, lh, b]
        vm, _ = self.roundtrip(vec_from_cols(cols))
        self.assertEqual(vm["pin_streams_stored"], 2)           # only a and b stored
        self.assertEqual(vm["pins_aliased"], 4)

    def test_pin_constant_in_some_segments_only(self):
        quiet = "0" * 2000 + "1" * 2000 + "".join(random.Random(2).choice("01") for _ in range(2000))
        vm, _ = self.roundtrip(vec_from_cols([quiet, quiet[::-1]]), seg_rows=2000)
        self.assertGreaterEqual(vm["pins_zero_or_ones"], 3)

    def test_ternary_pins_split_planes(self):
        rnd = random.Random(3)
        cols = ["".join(rnd.choice("HLX") for _ in range(999)),
                "".join(rnd.choice("01") for _ in range(999)),
                "".join(rnd.choice("01Z") for _ in range(999)),     # no X: mask symbol = max
                "X" * 999]
        for seg in (8, 1 << 24):
            vm, _ = self.roundtrip(vec_from_cols(cols), seg_rows=seg)
            self.assertEqual(vm["pins_ter"], 2)

    def test_real_small_patterns_if_present(self):
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "pat_original")
        for fid in ("001", "002", "015"):
            p = os.path.join(root, fid + ".pat")
            if not os.path.exists(p):
                self.skipTest("corpus not present")
            dst = os.path.join(self.d, fid + ".pzst")
            compress(p, dst, level=9, force_mode="planes")
            import zipfile
            with zipfile.ZipFile(p) as z:
                orig = {i.filename: z.read(i) for i in z.infolist()}
            self.assertEqual(decompress_to_memory(dst), orig)

    # ---------------------------------------------------------- integrity
    def test_corruption_detected_everywhere(self):
        _, dst = self.roundtrip(rand_vec(4000, 12, seed=9), level=9)
        good = rb(dst)
        rnd = random.Random(5)
        positions = list(range(len(good)))      # every single byte
        for pos in positions:
            bad = bytearray(good)
            bad[pos] ^= 0x5A
            wb(dst, bytes(bad))
            with self.assertRaises((PzstError, UnicodeDecodeError, MemoryError, OverflowError),
                                   msg=f"flip at {pos} not detected"):
                decompress_to_memory(dst)

    def test_truncation_detected(self):
        _, dst = self.roundtrip(rand_vec(4000, 12, seed=10), level=9)
        good = rb(dst)
        for cut in (6, 20, len(good) // 2, len(good) - 1):
            wb(dst, good[:cut])
            with self.assertRaises(PzstError):
                decompress_to_memory(dst)

    def test_writer_error_propagates(self):
        _, dst = self.roundtrip(rand_vec(4000, 12, seed=11))

        class Boom:
            def write(self, b):
                raise IOError("disk full")
        with self.assertRaises(IOError):
            for name, _, _, emit in iter_members(dst):
                emit(Boom())

    def test_bad_alias_reference_rejected(self):
        # hand-build a v3 file whose pin map points pin 0 at pin 1 (forward ref)
        from patzstd import planes
        W, rows = 2, 8
        tab = bytes([1, ord("0"), ord("1"), 0] * 2)
        cmap = struct.pack("<II", 1, planes.STORED)
        payload = bytes([0b01010101])
        meta = cmap + struct.pack("<IQ", 1, len(payload))
        body = (b"PZST\x03" + struct.pack("<I", 1) + struct.pack("<H", 11) + b"Vectors.vec"
                + struct.pack("<BQB", 6, rows * 3, 0) + struct.pack("<IQI", W, rows, 8)
                + struct.pack("<I", len(tab)) + tab + struct.pack("<I", 1)
                + struct.pack("<I", 1) + struct.pack("<I", len(meta)) + meta + payload
                + b"\0" * 16)
        p = os.path.join(self.d, "bad.pzst")
        wb(p, body)
        with self.assertRaises(PzstError):
            decompress_to_memory(p)


if __name__ == "__main__":
    unittest.main()
