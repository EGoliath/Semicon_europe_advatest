"""Unit tests / edge cases for the patzstd codec.

    .venv/bin/python -m unittest discover -s tests -v
"""
import os
import random
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from patzstd import compress, decompress, decompress_to_memory, PzstError  # noqa: E402
from patzstd.codec import iter_members  # noqa: E402

PROGRAM = (b'<?xml version="1.0" encoding="UTF-8"?>\n<Program>\n'
           b'  <Instrument id="P1,P2,P3,P4">\n'
           b'    <Instruction id="genVec" value="8"/>\n  </Instrument>\n</Program>\n')


def rb(p):
    with open(p, "rb") as f:
        return f.read()


def wb(p, data):
    with open(p, "wb") as f:
        f.write(data)


def make_pat(path, vec, program=PROGRAM, comments=b""):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Program.sprg", program)
        z.writestr("Vectors.vec", vec)
        z.writestr("Comments.cmt", comments)
    return {"Program.sprg": program, "Vectors.vec": vec, "Comments.cmt": comments}


def rand_vec(rows, width, alphabet_per_pin=None, seed=0):
    rnd = random.Random(seed)
    if alphabet_per_pin is None:
        alphabet_per_pin = [rnd.choice(["01", "HLX"[:2], "LX", "HX", "0"]) for _ in range(width)]
    lines = ("".join(rnd.choice(alphabet_per_pin[c]) for c in range(width))
             for _ in range(rows))
    return ("\n".join(lines) + "\n").encode()


class RoundTrip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def roundtrip(self, vec, expect_mode=None, chunk_rows=1 << 20, **kw):
        src = os.path.join(self.d, "in.pat")
        orig = make_pat(src, vec)
        dst = os.path.join(self.d, "x.pzst")
        rep = compress(src, dst, chunk_rows=chunk_rows, **kw)
        got = decompress_to_memory(dst)
        self.assertEqual(got, orig)
        vmode = next(m["mode"] for m in rep if m["name"] == "Vectors.vec")
        if expect_mode:
            self.assertEqual(vmode, expect_mode)
        return dst, vmode

    # --- mode selection ------------------------------------------------------
    def test_two_symbol_pins_use_bitpack(self):
        self.roundtrip(rand_vec(1000, 37), "bitpack")

    def test_three_symbol_pin_falls_back_to_transpose(self):
        self.roundtrip(rand_vec(500, 8, ["HLX"] + ["01"] * 7), "transpose")

    def test_third_symbol_appears_late(self):
        v = bytearray(rand_vec(3000, 6, ["01"] * 6))
        v[-3] = ord("X")             # 3rd symbol in the very last vector
        self.roundtrip(bytes(v), "transpose", chunk_rows=256)

    def test_constant_pins(self):
        self.roundtrip(rand_vec(200, 5, ["0", "X", "1", "L", "H"]), "bitpack")

    def test_ragged_lines_fall_back_to_raw(self):
        self.roundtrip(b"0101\n011\n0101\n", "raw")

    def test_missing_final_newline_raw(self):
        self.roundtrip(b"0101\n0110\n0101", "raw")

    def test_crlf_raw(self):
        self.roundtrip(b"0101\r\n0110\r\n", None)   # any mode, must be lossless

    def test_empty_vectors(self):
        self.roundtrip(b"", "raw")

    def test_single_vector(self):
        self.roundtrip(b"01HLX\n", "bitpack")

    # --- chunk boundaries ----------------------------------------------------
    def test_rows_not_multiple_of_chunk_or_8(self):
        for rows in (1, 7, 8, 9, 255, 256, 257, 1023):
            with self.subTest(rows=rows):
                self.roundtrip(rand_vec(rows, 11, seed=rows), "bitpack", chunk_rows=256)

    def test_forced_modes(self):
        v = rand_vec(777, 19)
        for mode in ("raw", "transpose", "bitpack"):
            with self.subTest(mode=mode):
                self.roundtrip(v, mode, force_mode=mode)

    def test_force_bitpack_impossible(self):
        with self.assertRaises(PzstError):
            self.roundtrip(rand_vec(50, 3, ["HLX"] * 3), force_mode="bitpack")

    def test_levels(self):
        v = rand_vec(2000, 64)
        for lvl in (1, 3, 9, 19):
            with self.subTest(level=lvl):
                self.roundtrip(v, "bitpack", level=lvl)

    # --- inputs / outputs ----------------------------------------------------
    def test_directory_input_and_pat_output(self):
        vec = rand_vec(300, 9)
        folder = os.path.join(self.d, "001.pat")
        os.mkdir(folder)
        files = {"Program.sprg": PROGRAM, "Vectors.vec": vec, "Comments.cmt": b""}
        for n, b in files.items():
            with open(os.path.join(folder, n), "wb") as f:
                f.write(b)
        dst = os.path.join(self.d, "001.pzst")
        compress(folder, dst)
        out_pat = os.path.join(self.d, "restored.pat")
        decompress(dst, out_pat, as_pat=True)
        with zipfile.ZipFile(out_pat) as z:
            self.assertEqual({n: z.read(n) for n in z.namelist()}, files)
        out_dir = os.path.join(self.d, "restored")
        decompress(dst, out_dir)
        for n, b in files.items():
            with open(os.path.join(out_dir, n), "rb") as f:
                self.assertEqual(f.read(), b)

    # --- integrity -----------------------------------------------------------
    def test_corruption_detected(self):
        dst, _ = self.roundtrip(rand_vec(5000, 16, seed=3), "bitpack")
        data = bytearray(rb(dst))
        bad = os.path.join(self.d, "bad.pzst")
        caught = 0
        for pos in range(20, len(data), max(1, len(data) // 25)):
            d2 = bytearray(data)
            d2[pos] ^= 0x55
            wb(bad, d2)
            try:
                decompress_to_memory(bad)
            except Exception:
                caught += 1
            else:
                self.fail(f"corruption at byte {pos} went undetected")
        self.assertGreater(caught, 0)

    def test_truncation_detected(self):
        dst, _ = self.roundtrip(rand_vec(5000, 16, seed=4), "bitpack")
        data = rb(dst)
        bad = os.path.join(self.d, "trunc.pzst")
        wb(bad, data[: len(data) // 2])
        with self.assertRaises(Exception):
            decompress_to_memory(bad)

    def test_not_a_pzst(self):
        p = os.path.join(self.d, "junk.pzst")
        import zstandard
        wb(p, zstandard.ZstdCompressor().compress(b"hello world"))
        with self.assertRaises(PzstError):
            decompress_to_memory(p)

    def test_unsafe_member_name_rejected(self):
        src = os.path.join(self.d, "evil.pat")
        with zipfile.ZipFile(src, "w") as z:
            z.writestr("../evil.txt", b"x")
        dst = os.path.join(self.d, "evil.pzst")
        compress(src, dst)
        with self.assertRaises(PzstError):
            decompress(dst, os.path.join(self.d, "out"))

    def test_member_order_preserved(self):
        dst, _ = self.roundtrip(rand_vec(10, 4))
        names = []
        for n, _, _, emit in iter_members(dst):
            names.append(n)
            with open(os.devnull, "wb") as sink:
                emit(sink)
        self.assertEqual(names, ["Program.sprg", "Vectors.vec", "Comments.cmt"])


class RealFiles(unittest.TestCase):
    """Round-trip the small real patterns if the dataset is present."""
    DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "pat_original")

    def test_small_real_patterns(self):
        if not os.path.isdir(self.DATA):
            self.skipTest("dataset not present")
        with tempfile.TemporaryDirectory() as d:
            for n in ("001.pat", "002.pat", "013.pat", "015.pat", "016.pat"):
                p = os.path.join(self.DATA, n)
                if not os.path.exists(p):
                    continue
                with self.subTest(file=n):
                    with zipfile.ZipFile(p) as z:
                        orig = {i: z.read(i) for i in z.namelist()}
                    dst = os.path.join(d, n + ".pzst")
                    compress(p, dst)
                    self.assertEqual(decompress_to_memory(dst), orig)


if __name__ == "__main__":
    unittest.main()
