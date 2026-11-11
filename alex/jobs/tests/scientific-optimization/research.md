# Logic minimization: from KDNF/KKNF to minimal forms

Written from standard textbook knowledge; no web sources were fetched. The classic references are given at the end.

## 1. The forms

| Abbrev. (DE) | English | What it is | Uniqueness |
|---|---|---|---|
| **KDNF** (kanonische disjunktive NF) | canonical DNF, *sum of minterms* (SOP) | OR of all minterms where f = 1; each term contains every variable | unique per function |
| **KKNF** (kanonische konjunktive NF) | canonical CNF, *product of maxterms* (POS) | AND of all maxterms where f = 0 | unique per function |
| DNF / KNF | DNF / CNF | any SOP / POS; terms may omit variables | many per function |
| **DMF** (disjunktive Minimalform) | minimal SOP | SOP with the fewest terms, then the fewest literals | not always unique |
| **KMF** (konjunktive Minimalform) | minimal POS | the dual of DMF: minimize the SOP of ¬f, then apply De Morgan | not always unique |
| Blake canonical form | complete sum | OR of **all** prime implicants | unique |
| ANF / Reed–Muller (Zhegalkin) | XOR of ANDs, positive literals only | polynomial over GF(2) | unique |
| ESOP | exclusive SOP | XOR of arbitrary products | many |

Terms used below:
- **Implicant:** a product term p with p ⇒ f.
- **Prime implicant (PI):** an implicant from which no literal can be removed.
- **Essential PI:** the only PI that covers some minterm.

Every DMF consists of PIs, which gives the standard two-step recipe: **(1) generate the PIs, (2) choose a minimum cover.**

**Don't-cares.** An incompletely specified function has an ON-set, an OFF-set and a DC-set. The DC minterms may be used to grow implicants but never need to be covered. This maps directly onto `X` in pattern data (see §4).

## 2. Algorithms

### Exact two-level
| Method | Idea | Complexity / limits |
|---|---|---|
| **Boolean algebra** | absorption `a + ab = a`, combining `ab + ab' = a`, consensus `ab + a'c + bc = ab + a'c` | manual, no optimality guarantee |
| **Karnaugh–Veitch map** (Veitch 1952, Karnaugh 1953) | Gray-coded grid; adjacent cells differ in one variable; circle maximal power-of-2 blocks (PIs), cover the 1s | visual, practical up to about 5–6 variables |
| **Quine–McCluskey** (Quine 1952, McCluskey 1956) | tabular: group minterms by the number of 1s and merge pairs that differ in one bit (`0-1-`) repeatedly; terms that never merge are the PIs | there can be up to ~3ⁿ/n PIs; practical up to about 10–15 variables |
| **Iterated consensus** | repeatedly add consensus terms and remove absorbed terms until stable; the result is the Blake canonical form | works directly from any SOP, no truth table needed |
| **PI chart + reductions** | the chart has rows = PIs and columns = minterms. Take the essential PIs; delete dominated rows and dominating columns; repeat (the cyclic core may remain) | polynomial reductions, then the hard core |
| **Petrick's method** (1956) | write the cover condition as a product of sums (`(P1+P3)(P2+P3)…`), multiply out to an SOP, pick the cheapest product | exponential; it is exact set cover |
| **Unate covering via ILP/SAT, branch & bound** | min Σcᵢxᵢ subject to every minterm covered; lower bounds from maximal independent sets (Coudert 1996, *Scherzo*) | the modern exact approach |

**Complexity.** Minimum DNF from a full truth table is NP-hard (Masek 1979; Allender et al. 2008). From an arbitrary formula it is Σ₂ᵖ-complete (Umans 2001). Exact methods therefore always hit a wall, and heuristics are the industrial norm.

### Implicit / symbolic (large n)
- **BDD / ROBDD** (Bryant 1986): a canonical DAG of a Boolean function, for a fixed variable order. Equivalence checks are O(1) after construction. The size depends heavily on the variable order; reordering heuristics exist (e.g. *sifting*, Rudell 1993).
- **ZDD** (Minato 1993): a BDD variant with a zero-suppression rule, very compact for **sparse sets of combinations**, i.e. sets of cubes.
- **Implicit PI generation** (Coudert & Madre 1992): computes all PIs as a BDD/ZDD. It handles functions with more than 10⁶ PIs without enumerating them.

### Heuristic two-level
- **Espresso** (Brayton, Hachtel, McMullen, Sangiovanni-Vincentelli 1984), the de-facto standard:
  - Data structure: *positional cube notation*, e.g. `01` = 0, `10` = 1, `11` = don't care per variable.
  - Main loop: `EXPAND` (grow each cube into a PI against the OFF-set), then `IRREDUNDANT` (drop cubes covered by others), then `REDUCE` (shrink cubes to escape a local minimum). Repeat until the cost stops improving, then run `LAST_GASP`.
  - Built on the *unate recursive paradigm* (fast tautology and complement checks via Shannon cofactors).
  - Variants: `espresso -Dexact`, Espresso-signature (McGeer et al. 1993).
- **Multi-output minimization:** shared product terms across outputs (PLA cost). Espresso does this natively.

### Multi-level & XOR
- **Algebraic factoring:** kernels and co-kernels (Brayton & McMullen 1982), as used in MIS, SIS and **ABC** (Mishchenko). In ABC: AIG rewriting, `resub`, `refactor`, `dc2`.
- **ESOP / Reed–Muller minimization:** EXORCISM (Mishchenko & Perkowski 2001). XOR forms can be exponentially smaller for parity-like functions.

## 3. Practical choice
| n (vars) | Use |
|---|---|
| ≤ 6 | K-map (manual) or Quine–McCluskey |
| ≤ ~15 | Quine–McCluskey + Petrick / ILP (exact) |
| ~15–50, explicit cubes | Espresso (heuristic), Espresso-exact if feasible |
| large / implicit | BDD/ZDD-based (implicit PIs), SAT-based exact cover |
| multi-level circuits | ABC / SIS |

Tools: `espresso` (Berkeley, open source), `ABC` (Berkeley), CUDD (BDD/ZDD library), Python `pyeda` (has espresso bindings), `sympy.logic.simplify_logic` / `SOPform` (Quine–McCluskey, small n).

## 4. Relevance to the compression challenge (assessment)
Logic minimization minimizes **circuit cost** (terms and literals), not **entropy**. It only helps compression where the data really is a low-complexity Boolean function. Mapping and caveats:

1. **Column-as-function.** Treat one pin's bit-plane over a block of 2ᵏ cycles as f(cycle-index bits). A DMF (or ESOP) is then a compact *program* for that column.
   - Should win: clocks, counters and constant or periodic pins, where SOP/ANF size is tiny.
   - Should lose: SCAN data (pseudo-random), where the PI count explodes.
   - Worth benchmarking against zstd per pin type.
2. **Don't-care `X` cannot be exploited by rewriting.** The challenge requires a **byte-exact** round-trip, so an `X` must come back as `X`. Store the X-mask (and the drive/expect masks) as **separate planes**. Those planes are highly structured: whole columns are X for long cycle ranges (seen in the 001 visualization). That is a good fit for cube/ZDD coding or run-length coding of the mask, with the value plane coded only where it is not X.
3. **ZDD / cube-set encoding of sparse planes.** H/L positions within mostly-L sections are sparse sets of (row, col) pairs. A ZDD or a cube cover is a candidate structured encoding to compare against zstd on the same plane.
4. **Reed–Muller / ANF** for XOR-structured data (LFSR/PRPG-generated scan stimulus is linear over GF(2)). If the scan stimulus comes from an LFSR, *linear algebra over GF(2)* (finding the seed or polynomial, e.g. with Berlekamp–Massey) can compress a whole channel to a seed plus a length. That is far stronger than SOP minimization and worth testing.
5. **Cost of decompression.** Evaluating an SOP per cycle is cheap and parallel (it maps well to hardware). Decompression speed is scored, so this is a plus *if* the forms are small.

**Expectation:** pure DMF/Espresso on raw scan bits will lose to zstd. Splitting into planes (X / drive-vs-expect / value) plus structured coding of the masks, and GF(2) linear modeling, are the promising angles.

## 5. References
- E. W. Veitch, "A chart method for simplifying truth functions", ACM, 1952.
- M. Karnaugh, "The map method for synthesis of combinational logic circuits", AIEE Trans., 1953.
- W. V. Quine, "The problem of simplifying truth functions", Amer. Math. Monthly, 1952.
- E. J. McCluskey, "Minimization of Boolean functions", Bell Syst. Tech. J., 1956.
- S. R. Petrick, "A direct determination of the irredundant forms of a Boolean function…", 1956.
- R. K. Brayton, G. D. Hachtel, C. McMullen, A. Sangiovanni-Vincentelli, *Logic Minimization Algorithms for VLSI Synthesis*, Kluwer, 1984 (Espresso).
- R. E. Bryant, "Graph-based algorithms for Boolean function manipulation", IEEE Trans. Comput., 1986.
- S. Minato, "Zero-suppressed BDDs for set manipulation in combinatorial problems", DAC 1993.
- O. Coudert, J. C. Madre, "Implicit and incremental computation of primes and essential primes of Boolean functions", DAC 1992.
- O. Coudert, "On solving covering problems", DAC 1996.
- C. Umans, "The minimum equivalent DNF problem and shortest implicants", JCSS, 2001.
- E. Allender, L. Hellerstein, P. McCabe, T. Pitassi, M. Saks, "Minimizing DNF formulas and AC0 circuits given a truth table", SIAM J. Comput., 2008.
- A. Mishchenko, M. Perkowski, "Fast heuristic minimization of exclusive-sums-of-products", RM Workshop 2001.
- R. Rudell, "Dynamic variable ordering for ordered binary decision diagrams", ICCAD 1993.
