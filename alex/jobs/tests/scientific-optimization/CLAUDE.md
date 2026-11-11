# CLAUDE.md: tests/scientific-optimization

Local sub-task of the main challenge (see `../../CLAUDE.md`): check whether logic-minimization theory (KDNF/KKNF → DMF/KMF, Quine–McCluskey, Espresso, BDD/ZDD, Reed–Muller) can help compress pattern data.

## Files
- `research.md`: the survey of forms and algorithms, plus an assessment for the challenge.

## Goals
- [x] Survey the algorithms that take canonical forms (KDNF, KKNF) to minimal forms.
- [ ] Benchmark column-as-function (SOP/ESOP per pin over 2^k cycles) against zstd, per pin type.
- [ ] Split the data into planes (X-mask / drive-vs-expect / value) and code the masks with structured methods (cube/ZDD/RLE) against zstd.
- [ ] Test the GF(2) linear model (Berlekamp–Massey) on scan channels to see whether they are LFSR-generated.

## Constraints
- The round-trip must be byte-exact, so `X` can't be used as a free don't-care. It has to be stored (as a mask).
