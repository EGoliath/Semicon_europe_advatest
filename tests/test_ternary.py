"""Tests for the ternary (3^5 -> 1 byte) codecs.

    .venv/bin/python -m unittest tests.test_ternary -v
"""
import itertools
import os
import random
import struct
import sys
import tempfile
import unittest
import zipfile

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from patzstd import ternary as T  # noqa: E402
from patzstd import compress, decompress_to_memory, PzstError  # noqa: E402
from patzstd import codec  # noqa: E402

ALPH = np.frombuffer(b"01X", np.uint8)
ALL5 = list(itertools.product(b"01X", repeat=5))            # 243 groups


def wb(p, data):
    with open(p, "wb") as f:
        f.write(data)


def rb(p):
    with open(p, "rb") as f:
        return f.read()


class StreamCodec(unittest.TestCase):
    """Generic stream codec: C kernel and pure-Python reference."""

    def both(self, data, alph=ALPH):
        enc_c = bytes(T.stream_encode(data, alph))
        enc_r = T.stream_encode_ref(data, alph)
        self.assertEqual(enc_c, enc_r, "C and reference encoder differ")
        for use_lut in (True, False):
            self.assertEqual(bytes(T.stream_decode(enc_c, alph, len(data), use_lut)), data)
        self.assertEqual(T.stream_decode_ref(enc_c, alph, len(data)), data)
        return enc_c

    def test_all_243_groups(self):
        seen = set()
        for g in ALL5:
            enc = self.both(bytes(g))
            self.assertEqual(len(enc), 1)                     # 5 symbols -> 1 byte
            seen.add(enc[0])
            d = [b"01X".index(x) for x in g]
            self.assertEqual(enc[0], d[0] + 3 * d[1] + 9 * d[2] + 27 * d[3] + 81 * d[4])
        self.assertEqual(seen, set(range(243)))

    def test_all_groups_concatenated(self):
        data = b"".join(bytes(g) for g in ALL5)
        self.assertEqual(len(self.both(data)), 243)

    def test_incomplete_groups(self):
        for k in range(1, 5):
            for g in itertools.product(b"01X", repeat=k):
                for tail in (b"", b"\n", b"<", b"\n01X10"):
                    with self.subTest(k=k, g=g, tail=tail):
                        enc = self.both(bytes(g) + tail)
                        self.assertEqual(enc[0], 243 + k)     # partial-group token

    def test_lengths_0_to_30_and_newlines(self):
        rnd = random.Random(1)
        for n in range(31):
            s = bytes(rnd.choice(b"01X\n") for _ in range(n))
            self.both(s)

    def test_empty(self):
        self.assertEqual(self.both(b""), b"")

    def test_unexpected_symbols_are_literals(self):
        data = b"01X\x00\xff\xf3\xf8HLZ\r\n<?xml?>"
        enc = self.both(data)
        self.assertIn(248, enc)

    def test_random_bytes(self):
        rnd = random.Random(7)
        for _ in range(50):
            n = rnd.randrange(0, 500)
            s = bytes(rnd.choice(b"01X01X01X\nHL\x00\xfe") for _ in range(n))
            self.both(s)

    def test_other_alphabets(self):
        for a in (b"HLX", b"LH\x00", b"abc"):
            al = np.frombuffer(a, np.uint8)
            self.both(a * 7 + b"\n" + a[::-1] * 3 + b"q", al)

    def test_stream_alphabet_choice(self):
        a = T.stream_alphabet(b"1111000XX\n\n\n\n\n\nH")
        self.assertEqual(bytes(a), b"10X")                    # newline excluded
        a = T.stream_alphabet(b"\n\n")
        self.assertEqual(len(set(a.tolist())), 3)
        self.assertNotIn(10, a)

    # --- malformed input -------------------------------------------------
    def bad(self, enc, n, alph=ALPH):
        with self.assertRaises(T.TernaryError):
            T.stream_decode(bytes(enc), alph, n)
        with self.assertRaises(T.TernaryError):
            T.stream_decode_ref(bytes(enc), alph, n)

    def test_invalid_tokens(self):
        for tok in range(249, 256):
            self.bad([tok], 5)

    def test_truncated_tokens(self):
        for tok in (244, 245, 246, 247, 248):
            self.bad([tok], 4)

    def test_partial_value_out_of_range(self):
        for k, lim in zip(range(1, 5), (3, 9, 27, 81)):
            self.bad([243 + k, lim], k)
            self.assertEqual(len(T.stream_decode(bytes([243 + k, lim - 1]), ALPH, k)), k)

    def test_non_canonical_literals(self):
        for b in (ord("0"), ord("1"), ord("X"), 10):
            self.bad([248, b], 1)

    def test_length_mismatch(self):
        self.bad([0], 4)          # decodes to 5 bytes, 4 expected
        self.bad([0], 6)


class GridCodecs(unittest.TestCase):
    def grid(self, rows, W, pin_alph, seed=0):
        rnd = random.Random(seed)
        lines = ["".join(rnd.choice(pin_alph[c]) for c in range(W)) for _ in range(rows)]
        return ("\n".join(lines) + "\n").encode() if rows else b""

    def test_row_all_243_groups(self):
        g = b"\n".join(bytes(x) for x in ALL5) + b"\n"         # 243 rows, W=5
        enc = T.row_pack(g, 243, 5, ALPH)
        self.assertEqual(sorted(enc.tolist()), list(range(243)))
        self.assertEqual(bytes(T.row_unpack(enc, 243, 5, ALPH)), g)

    def test_row_widths_and_ref(self):
        for W in range(1, 13):
            for rows in (1, 3, 17):
                with self.subTest(W=W, rows=rows):
                    g = self.grid(rows, W, ["01X"] * W, seed=W * 100 + rows)
                    e = T.row_pack(g, rows, W, ALPH)
                    self.assertEqual(e.tolist(), T.row_pack_ref(g, rows, W, ALPH).tolist())
                    for lut in (True, False):
                        self.assertEqual(bytes(T.row_unpack(e, rows, W, ALPH, lut)), g)
                    self.assertEqual(bytes(T.row_unpack_ref(e, rows, W, ALPH)), g)
                    self.assertEqual(len(e), rows * ((W + 4) // 5))

    def test_row_rejects(self):
        with self.assertRaises(T.TernaryError):
            T.row_pack(b"01H\n", 1, 3, ALPH)                  # symbol not in alphabet
        with self.assertRaises(T.TernaryError):
            T.row_unpack(bytes([243]), 1, 5, ALPH)            # >= 243
        with self.assertRaises(T.TernaryError):
            T.row_unpack(bytes([27]), 1, 3, ALPH)             # partial group >= 3^3

    def test_mixed_classes_and_ref(self):
        pins = ["01", "HLX", "X", "0", "LH", "HLX", "1X", "X"]
        for rows in (1, 4, 5, 8, 39, 40, 41, 81, 333):
            with self.subTest(rows=rows):
                W = len(pins)
                g = self.grid(rows, W, pins, seed=rows)
                pres = np.zeros((W, 256), np.uint8)
                a = np.frombuffer(g, np.uint8).reshape(rows, W + 1)
                for c in range(W):
                    pres[c, np.unique(a[:, c])] = 1
                for force in (False, True):
                    cls, alph, lut = T.pin_classes(pres, force)
                    e = T.mixed_pack(g, rows, W, cls, lut)
                    self.assertEqual(e.tolist(), T.mixed_pack_ref(g, rows, W, cls, lut).tolist())
                    self.assertEqual(len(e), T.mixed_size(rows, cls))
                    for use_lut in (True, False):
                        self.assertEqual(bytes(T.mixed_unpack(e, rows, W, cls, alph, use_lut)), g)
                    self.assertEqual(bytes(T.mixed_unpack_ref(e, rows, W, cls, alph)), g)

    def test_mixed_all_243_on_one_pin(self):
        col = b"".join(bytes(x) for x in ALL5)                 # 1215 vectors, 1 pin
        g = b"\n".join(bytes([c]) for c in col) + b"\n"
        pres = np.zeros((1, 256), np.uint8)
        pres[0, list(b"01X")] = 1
        cls, alph, lut = T.pin_classes(pres)
        e = T.mixed_pack(g, len(col), 1, cls, lut)
        self.assertEqual(len(e), 243)
        self.assertEqual(bytes(T.mixed_unpack(e, len(col), 1, cls, alph)), g)

    def test_mixed_rejects(self):
        pres = np.zeros((1, 256), np.uint8)
        pres[0, list(b"01X")] = 1
        cls, alph, lut = T.pin_classes(pres)
        with self.assertRaises(T.TernaryError):
            T.mixed_unpack(bytes([243]), 5, 1, cls, alph)
        with self.assertRaises(T.TernaryError):
            T.mixed_pack(b"0\nH\n", 2, 1, cls, lut)
        pres[0, ord("H")] = 1
        with self.assertRaises(T.TernaryError):
            T.pin_classes(pres)                                # 4 symbols


class Container(unittest.TestCase):
    """End to end through compress()/decompress with every new mode."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def pat(self, vec, prog=b"<Program>\n</Program>\n"):
        p = os.path.join(self.d, "in.pat")
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("Program.sprg", prog)
            z.writestr("Vectors.vec", vec)
            z.writestr("Comments.cmt", b"")
        return p, {"Program.sprg": prog, "Vectors.vec": vec, "Comments.cmt": b""}

    def rt(self, vec, mode, level=3, expect=None):
        src, orig = self.pat(vec)
        dst = os.path.join(self.d, f"o_{mode}_{level}.pzst")
        rep = compress(src, dst, level=level, force_mode=mode)
        self.assertEqual(decompress_to_memory(dst), orig)
        vm = next(m for m in rep if m["name"] == "Vectors.vec")
        if expect:
            self.assertEqual(vm["mode"], expect)
        return dst, rep

    def test_modes_levels(self):
        rnd = random.Random(3)
        vec = "".join("".join(rnd.choice(p) for p in ["01", "X", "01X", "1", "0X"]) + "\n"
                      for _ in range(3001)).encode()
        for mode, exp in (("t5", "t5"), ("t5row", "t5row"), ("t5col", "t5col"),
                          ("mixed", "mixed")):
            for level in (None, 1, 3, 19):
                with self.subTest(mode=mode, level=level):
                    self.rt(vec, mode, level, exp)

    def test_plain_container_is_not_zstd(self):
        dst, _ = self.rt(b"01X\n" * 10, "t5", None)
        self.assertEqual(rb(dst)[:4], b"PZST")
        dst, _ = self.rt(b"01X\n" * 10, "t5", 3)
        self.assertEqual(rb(dst)[:4], codec.ZSTD_MAGIC)

    def test_fallbacks(self):
        five = b"01HLX\n" * 50                                # 5 symbols in file
        self.rt(five, "t5row", 3, "t5")                       # -> generic stream
        self.rt(five, "mixed", 3, "mixed")                    # per pin <= 3: fine
        ragged = b"01X\n0X\n1\n"
        for m in ("t5row", "t5col", "mixed"):
            self.rt(ragged, m, 3, "t5")

    def test_empty_and_tiny(self):
        for m in ("t5", "t5row", "t5col", "mixed"):
            self.rt(b"", m, 3)
            self.rt(b"X\n", m, None)

    def test_mixed_raw_and_packed_blocks(self):
        old = codec.T5_BLOCK
        codec.T5_BLOCK = 1024
        try:
            rnd = random.Random(5)
            noise = bytes(rnd.randrange(256) for _ in range(3000))        # grows -> raw
            vec = b"01X10\n" * 400 + noise + b"X0\n" * 600 + b"\x00\r\n"
            dst, rep = self.rt(vec, "t5", None)
            vm = next(m for m in rep if m["name"] == "Vectors.vec")
            self.assertGreater(vm["t5_blocks"], 0)
            self.assertGreater(vm["raw_blocks"], 0)
            prog = next(m for m in rep if m["name"] == "Program.sprg")
            self.assertEqual(prog["raw_blocks"], 1)                       # XML stays raw
        finally:
            codec.T5_BLOCK = old

    def test_corruption_rejected(self):
        rnd = random.Random(9)
        vec = "".join("".join(rnd.choice("01X") for _ in range(13)) + "\n"
                      for _ in range(2000)).encode()
        for mode in ("t5", "t5row", "mixed"):
            dst, _ = self.rt(vec, mode, None)                  # plain: bytes reach decoder
            data = bytearray(rb(dst))
            bad = os.path.join(self.d, "bad.pzst")
            for pos in range(9, len(data), max(1, len(data) // 40)):
                d2 = bytearray(data)
                d2[pos] ^= 0xA5
                wb(bad, d2)
                with self.subTest(mode=mode, pos=pos):
                    with self.assertRaises(Exception):
                        decompress_to_memory(bad)
            wb(bad, data[: len(data) - 7])
            with self.assertRaises(Exception):
                decompress_to_memory(bad)

    def test_crafted_bad_headers(self):
        def container(member_payload, mode, size):
            name = b"Vectors.vec"
            return (codec.MAGIC + struct.pack("<I", 1) + struct.pack("<H", len(name)) + name
                    + struct.pack("<BQ", mode, size) + member_payload + b"\0" * 16)
        cases = {
            "unknown block type": (bytes([9]) + struct.pack("<I", 5), codec.MODE_T5S, 5),
            "block longer than member": (bytes([1]) + struct.pack("<I", 99) + b"x" * 99,
                                         codec.MODE_T5S, 5),
            "zero-length block": (bytes([1]) + struct.pack("<I", 0), codec.MODE_T5S, 5),
            "duplicate alphabet": (bytes([2]) + struct.pack("<II", 5, 1) + b"00X" + b"\0",
                                   codec.MODE_T5S, 5),
            "bad pin class": (struct.pack("<IQI", 1, 1, 1) + b"\x07" + b"01X" + b"\0",
                              codec.MODE_MIXED, 2),
            "bad row alphabet": (struct.pack("<IQI", 1, 1, 1) + b"\n01" + b"\0",
                                 codec.MODE_T5ROW, 2),
            "unknown mode": (b"", 42, 1),
        }
        p = os.path.join(self.d, "crafted.pzst")
        for what, args in cases.items():
            with self.subTest(what):
                wb(p, container(*args))
                with self.assertRaises(PzstError):
                    decompress_to_memory(p)

    def test_not_a_container(self):
        p = os.path.join(self.d, "junk.pzst")
        wb(p, b"hello")
        with self.assertRaises(PzstError):
            decompress_to_memory(p)


class BestHybrid(Container):
    """'best' = earlier auto choice (bitpack/transpose) vs mixed, keep smaller."""

    def vec(self, pins, rows=4000, seed=11):
        rnd = random.Random(seed)
        return "".join("".join(rnd.choice(p) for p in pins) + "\n" for _ in range(rows)).encode()

    def test_binary_file_roundtrip_and_choice(self):
        dst, rep = self.rt(self.vec(["01"] * 20 + ["X"] * 4), "best")
        vm = next(m for m in rep if m["name"] == "Vectors.vec")
        self.assertIn(vm["mode"], ("best:bitpack", "best:mixed"))
        win = vm["mode"].split(":")[1]
        self.assertEqual(vm[f"trial_{win}"], min(vm["trial_bitpack"], vm["trial_mixed"]))

    def test_hlx_pins_compare_transpose_and_mixed(self):
        dst, rep = self.rt(self.vec(["01", "HLX", "HLX", "X", "LH"] * 6), "best")
        vm = next(m for m in rep if m["name"] == "Vectors.vec")
        self.assertEqual(set(k for k in vm if k.startswith("trial_")),
                         {"trial_transpose", "trial_mixed"})

    def test_output_not_larger_than_either_mode(self):
        v = self.vec(["01", "HLX", "X", "0", "10", "HLX"] * 5, rows=20000)
        sizes = {}
        for mode in (None, "mixed", "best"):
            dst, _ = self.rt(v, mode, 9)
            sizes[mode] = os.path.getsize(dst)
        self.assertLessEqual(sizes["best"], min(sizes[None], sizes["mixed"]) + 64)

    def test_packing_only(self):
        self.rt(self.vec(["01", "HLX", "X"] * 3), "best", None)

    def test_not_a_grid_and_no_candidates(self):
        self.rt(b"01X\n0X\n", "best", 3, "raw")             # ragged -> raw like auto
        self.rt(self.vec(["01HL"] * 3, rows=300), "best", 3)  # 4 symbols: only transpose

    def test_frames_are_concatenated_and_checked(self):
        dst, _ = self.rt(self.vec(["01"] * 10), "best", 3)
        data = rb(dst)
        self.assertGreaterEqual(data.count(codec.ZSTD_MAGIC), 2)  # >= 2 zstd frames
        bad = os.path.join(self.d, "bad.pzst")
        for pos in range(8, len(data), max(1, len(data) // 30)):
            d2 = bytearray(data)
            d2[pos] ^= 0x3C
            wb(bad, d2)
            with self.subTest(pos=pos):
                with self.assertRaises(Exception):
                    decompress_to_memory(bad)


class RealFiles(unittest.TestCase):
    DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "pat_original")

    def test_small_real_files_all_modes(self):
        if not os.path.isdir(self.DATA):
            self.skipTest("dataset not present")
        with tempfile.TemporaryDirectory() as d:
            for n in ("001.pat", "002.pat", "013.pat", "015.pat", "016.pat"):
                p = os.path.join(self.DATA, n)
                with zipfile.ZipFile(p) as z:
                    orig = {i: z.read(i) for i in z.namelist()}
                for mode in ("t5", "t5row", "t5col", "mixed", "best"):
                    for level in (None, 3):
                        with self.subTest(file=n, mode=mode, level=level):
                            dst = os.path.join(d, "x.pzst")
                            compress(p, dst, level=level, force_mode=mode)
                            self.assertEqual(decompress_to_memory(dst), orig)


if __name__ == "__main__":
    unittest.main()
