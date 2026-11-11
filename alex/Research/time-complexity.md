# Time and space complexity of two lossless compressors for ATE vector files

This note covers **zstd** (the baseline) and **pack**, the per-column bit-plane transform followed by zstd in `jobs/tests/ClaudeTries/tries.c`.

## Notation

- **Input** is `Vectors.vec`: $M$ lines (vectors) of $N$ cells (pins), one byte per cell. Any byte value is allowed in a cell.
- Each line ends with an EOL of $e \in \{1,2\}$ bytes (LF or CRLF). The last line may lack it. $e = 0$ means a single line with no EOL.
- **Size:**
  $$n = M(N+e) - [\text{no final EOL}]\cdot e ,\qquad MN \le n \le 3MN \quad (M,N\ge 1).$$
  The lower bound holds because $n \ge MN + (M-1)e$; the upper bound because $e \le 2 \le 2N$. So $n = \Theta(MN)$ with the explicit constants 1 and 3.
- **Scope:** only the vector stream. `Program.sprg` and `Comments.cmt` are excluded.

---

## 1. Summary

Every bound below holds **for all $M,N \ge 1$** with the constants stated in §3–§4. It therefore holds in the naive two-variable sense and in Howell's stricter $\hat O,\hat\Omega,\hat\Theta,\hat o,\hat\omega$ sense (§2.3).

- $T$ counts RAM steps (§2.1).
- $L$ (the zstd level) and $B = 4$ MiB (pack's block budget) are fixed constants.
- "o / ω" give the exact criterion, followed by examples.

| Algorithm · measure | $O$ | $\Omega$ | $\Theta$ | $o(g)$ holds iff … (examples) | $\omega(h)$ holds iff … (examples) |
|---|---|---|---|---|---|
| zstd · compress | $O(MN)$ | $\Omega(MN)$, on **every** input | $\Theta(MN)=\Theta(n)$ | $MN/g\to 0$: $MN\log(MN)$, $(MN)^{1+\varepsilon}$, $M^2N$, $MN^2$. Never $o(MN)$. | $h/(MN)\to 0$, $h$ nondecreasing: $M+N$, $\sqrt{MN}$, $MN/\log_2(MN{+}1)$. Never $\omega(MN)$. |
| zstd · decompress | $O(MN)$ | $\Omega(MN)$ | $\Theta(MN)$ | same | same |
| zstd · space (enc, dec) | $O(1)$ | $\Omega(1)$ | $\Theta(1)$, about $2^{W_L}$ plus tables | $o(g)$ for every $g\to\infty$ ($o(M)$, $o(N)$, …). Not $o(1)$. | Only $\omega(h)$ with $h\to 0$. Not $\omega(1)$. |
| pack · compress | $O(MN)$ | $\Omega(MN)$, on every valid input | $\Theta(MN)$ | as zstd | as zstd |
| pack · decompress | $O(MN)$ | $\Omega(MN)$ | $\Theta(MN)$ | as zstd | as zstd |
| pack · space (enc) | $O(N)$, at most $2B+1065N+O(1)$ bytes | $\Omega(N)$, at least $512N$ bytes | $\Theta(N)$ (constant in $M$) | $o(MN)$, $o(N\log N)$. Not $o(N)$. | $\omega(1)$, $\omega(\log N)$. Not $\omega(N)$. |
| pack · space (dec) | $O(N)$, at most $4B+306N+O(1)$ bytes | $\Omega(N)$ | $\Theta(N)$ (constant in $M$) | as above | as above |

**Per variable.** With $N$ fixed, every time bound is $\Theta(M)$ with constants linear in $N$. With $M$ fixed, every time bound is $\Theta(N)$.

**Best case = worst case.** The order is $\Theta(MN)$ for every input. Only the constants depend on the content.

**What separates the two methods in practice** is a constant factor, not the order (§4.5). pack hands zstd roughly $\sum_c b_c\,M/8$ bytes instead of $n$. On 003 that is about $8\times$ fewer.

---

## 2. Model and definitions

### 2.1 Machine model
- Word-RAM with $w = 64$-bit words and unit-cost byte and word operations.
- **A step** is one execution of an innermost loop body. One byte processed by `memset`, `memcpy`, `memchr` or `memcmp` is also one step. Each such step is a bounded number of machine instructions, independent of the input.
- Time is the number of steps. Seconds differ from steps only by a machine constant.
- **Not counted:**
  - disk I/O;
  - the OS work behind `MapViewOfFile` (the input is memory-mapped by `map_file`);
  - `fwrite` beyond copying the bytes into the stdio buffer.
- Touching a mapped byte counts as one read.
- `malloc` counts $O(1)$. Pages are paid for when they are first written.
- **Fixed constants (not inputs):**
  - the zstd level $L$, and with it the parameter row $(W, C, H, S, \text{mm}, \text{TL}, \text{strategy})$;
  - zstd's block size $2^{17}$;
  - pack's `BLOCK` $= B = 4\cdot2^{20}$.

### 2.2 One-variable notation (CLRS ch. 3; Knuth 1976)
For $f,g:\mathbb N\to\mathbb R_{\ge0}$:
- $f\in O(g)$ iff $\exists c>0,n_0\ \forall n\ge n_0: f(n)\le c\,g(n)$.
- $f\in\Omega(g)$ iff $\exists c>0,n_0\ \forall n\ge n_0: f(n)\ge c\,g(n)$.
- $\Theta(g)=O(g)\cap\Omega(g)$.
- $f\in o(g)$ iff $\forall c>0\ \exists n_0\ \forall n\ge n_0: f(n)< c\,g(n)$.
- $f\in\omega(g)$ iff $\forall c>0\ \exists n_0\ \forall n\ge n_0: f(n)> c\,g(n)$.

Knuth's note fixed $\Omega$ in this "lower bound" sense and introduced $\Theta$.

### 2.3 Several variables (Howell 2008)
**The naive extension.** Howell calls it $O_\forall$. It requires $g(n_1,\dots,n_k)\le c f(n_1,\dots,n_k)$ only when *all* $n_j\ge N_0$.

**Why that is not enough.** Howell shows that this definition, and the alternative $O_\exists$ (inequality whenever *some* $n_j \ge N_0$), break rules that analyses routinely use. Examples are summing over a loop index (his Property 2) and dropping lower-order terms (Property 3).

**Howell's definition.** He defines
$$\hat f(n_1,\dots,n_k)=\max\{f(i_1,\dots,i_k)\mid 0\le i_j\le n_j\}.$$
Then $g\in\hat O(f)$ iff there exist $c>0$ and $N_0$ such that, for all $n_1,\dots,n_k\ge N_0$,
$$g\le c f\quad(3.1)\qquad\text{and}\qquad \hat g\le c\hat f\quad(3.2).$$
- $\hat\Omega$ reverses both inequalities (4.1, 4.2).
- $\hat\Theta=\hat O\cap\hat\Omega$.
- $\hat o$ and $\hat\omega$ use strict inequalities "for every $c>0$" (5.1–5.4).
- I checked these definitions against the text of the report.

**How this document applies it.**
- Every time function $T(M,N)$ is defined for $M,N\ge1$. For $M=0$ or $N=0$ we set $T(M,N) := 0$ (no such inputs exist), so Howell's functions on $\mathbb N^2$ apply.
- Every bound we prove has the form
  $$c_1\,MN\ \le\ T(M,N)\ \le\ c_2\,MN\qquad\text{for all }M,N\ge1 .$$
  Since $MN$ is nondecreasing, $\widehat{MN}=MN$.
  - The upper bound gives $\hat T\le c_2 MN$.
  - The lower bound gives $\hat T\ge T\ge c_1MN$.
- So (3.1), (3.2), (4.1) and (4.2) hold with $N_0=1$. Hence $T\in\hat\Theta(MN)$, and also $T\in\Theta_\forall(MN)$ and $\Theta_\exists(MN)$.

---

## 3. Algorithm 1: zstd (baseline)

**Use in `tries.c`.**
- `zstd_enc` feeds the raw bytes in 4 MiB pieces to `ZSTD_compressStream2(..., ZSTD_e_continue)`. `zw_close` ends the frame with `ZSTD_e_end`.
- `zstd_dec` calls `ZSTD_decompressStream` into a 4 MiB buffer.
- Long-distance matching is off unless `-long` is given, and `-long` is not analysed here.

**Sources.** All zstd citations are to tag **v1.5.7**, raw files from `raw.githubusercontent.com/facebook/zstd/v1.5.7/…`. I read them for this note; line numbers are from those files.

**What kind of proof this is.** zstd's authors publish no complexity proof. The per-byte bounds below come from the loop structure of the cited functions. They are worst-case bounds with large constants. The "typical" amortized behaviour is a separate, weaker statement (§3.3).

### 3.1 Parameters actually used
`lib/compress/clevels.h:25–50` defines `ZSTD_defaultCParameters`. The row group "for any srcSize > 256 KB" is:

```
    /* W,  C,  H,  S,  L, TL, strat */
    { 19, 13, 14,  1,  7,  0, ZSTD_fast    },  /* level  1 */
    { 21, 16, 17,  1,  5,  0, ZSTD_dfast   },  /* level  3 */
    { 22, 20, 21,  4,  5, 16, ZSTD_lazy2   },  /* level  9 */
    { 23, 24, 22,  7,  3,256, ZSTD_btultra2},  /* level 19 */
```

**Why this row group applies.**
- `ZSTD_getCParams_internal` (`zstd_compress.c:~7760`) selects `tableID = (rSize <= 256 KB) + (rSize <= 128 KB) + (rSize <= 16 KB)`.
- With streaming and a first call of `ZSTD_e_continue`, the source size stays unknown. Only `ZSTD_e_end` on the first call sets it: `if (endOp == ZSTD_e_end) cctx->pledgedSrcSizePlusOne = inSize + 1;` (`zstd_compress.c:6366`).
- So `tableID = 0` and the row above applies for every input size.

**Other facts used below.**
- **Match finder at level 9.** `ZSTD_resolveRowMatchFinderMode` (`zstd_compress.c:238–245`) enables the row-based finder for greedy/lazy/lazy2 when `windowLog > 14`, so level 9 uses it.
- **Block size.** `ZSTD_BLOCKSIZELOG_MAX 17` (`zstd.h:147`). RFC 8878 §3.1.1.2.4: Block_Maximum_Size = min(Window_Size, 128 KB).
- **Pre-splitting.** `ZSTD_optimalBlockSize` and `zstd_preSplit.c` may cut a 128 KiB block. `ZSTD_splitBlock_byChunks` returns multiples of `CHUNKSIZE (8 << 10)`, and `ZSTD_splitBlock_fromBorders` returns 32, 64, 96 or 128 KiB. So every block except the last is at least 8 KiB, and the number of blocks is at most $n/2^{13}+1$.

### 3.2 Compression upper bound
Fix a level $L$ with searchLog $S$. Let $\Lambda = 2^{17}$ be the block size.

**Lemma Z1 (match-length extension).** Every `ZSTD_count(ip, match, iLimit)` call is bounded by the *current block's* end, `iend = istart + srcSize`. So it costs $O(1+\ell)$ steps, where $\ell \le \Lambda$ is its result.
- Seen in `ZSTD_compressBlock_lazy_generic` (`zstd_lazy.c:1516ff`), `ZSTD_HcFindBestMatch` (`:667`), `ZSTD_RowFindBestMatch` (`:1141`), `ZSTD_insertBt1` (`zstd_opt.c:442`) and the fast/dfast loops.

**Lemma Z2 (bounded candidates per search).**
- **Hash chain**, `ZSTD_HcFindBestMatch`: `U32 nbAttempts = 1U << cParams->searchLog;` (`zstd_lazy.c:689`) with loop `for ( ; (matchIndex>=lowLimit) & (nbAttempts>0) ; nbAttempts--)` (`:708`).
- **Row finder**, `ZSTD_RowFindBestMatch`:
  - `const U32 cappedSearchLog = MIN(cParams->searchLog, rowLog);` and `U32 nbAttempts = 1U << cappedSearchLog;` (`:1166–1169`);
  - `rowLog = BOUNDED(4, ms->cParams.searchLog, 6)` (`:1532`);
  - `ZSTD_ROW_HASH_MAX_ENTRIES 64` (`:780`).
- **Binary tree**, `ZSTD_insertBt1`: `U32 nbCompares = 1U << cParams->searchLog;` (`zstd_opt.c:474`).
- **All matches**, `ZSTD_insertBtAndGetAllMatches` (`zstd_opt.c:590`): `nbCompares = 1U << cParams->searchLog` (`:626`). It stops if `(matchLength > ZSTD_OPT_NUM) | (ip+matchLength == iLimit)` (`:753–756`), with `ZSTD_OPT_NUM (1<<12)` (`lib/common/zstd_internal.h:62`).
- In every case one search does at most $2^S$ (or $2^{\min(S,\text{rowLog})}$) candidate probes. Each probe is $O(1)$ plus one `ZSTD_count`, so a search costs $O(2^S(1+\Lambda))$.

**Lemma Z3 (each position searched at most once).** This holds in `ZSTD_compressBlock_lazy_generic`.
1. When `matchLength < 4`: `ip += step` with `step = ((ip-anchor) >> kSearchStrength) + 1` (`zstd_lazy.c:1614`), where `kSearchStrength 8`.
2. In the lazy look-ahead, `ip++` comes before every search (`:1631`, `:1667`).
3. The improvement test at depth 1 is `gain2 = ml2*4 - ZSTD_highbit32(ofbCandidate)` against `gain1 = matchLength*4 - ZSTD_highbit32(offBase) + 4` (`:1657–1658`); at depth 2 it is `… + 7` (`:1693–1694`). When the test succeeds, `continue` restarts the look-ahead from the new `ip`.
4. When no improvement is found, the loop breaks. The kept match starts at `start` $\ge$ (last searched position) $-2$ and has length $\ge 4$.
5. The sequence is then stored with `anchor = ip = start + matchLength;` (`:1725`).
6. The backward "catch up" lowers `start` and raises `matchLength` by the same amount, so `start + matchLength` does not change.

So the next search position is strictly greater than every earlier one. A block of $\lambda\le\Lambda$ bytes has at most $\lambda$ searches. Table insertion (hash chain or row update) touches each position at most once at $O(1)$ steps. The immediate-repcode loop (`:1757–1766`) advances `ip += matchLength` over the bytes it counted.

**Lemma Z4 (optimal parser, levels 16–22).** This covers `ZSTD_compressBlock_opt_generic` and `ZSTD_updateTree_internal`.
- **Tree insertion.** `idx += forward` (`zstd_opt.c:576`) with `forward ≥ 1`, which `ZSTD_insertBt1` asserts. Its speed guard is `if (bestLength > 384) positions = MIN(192, (U32)(bestLength - 384));` and `return MAX(positions, matchEndIdx - (curr + 8));` (`:554–556`). So each position is inserted at most once, at $O(2^S(1+\Lambda))$ steps.
- **The forward pass** covers $\text{cur}=1..\text{last\_pos}$, and afterwards `ip` advances by `last_pos` (`:1352`, `:1420–1431`). So each position is a "cur" at most once.
- **Early exits.**
  - `sufficient_len = MIN(cParams->targetLength, ZSTD_OPT_NUM -1)` (`:1096`).
  - "large match → immediate encoding" when `maxML > sufficient_len` (`:1160–1169`).
  - `(longestML > sufficient_len) || (cur + longestML >= ZSTD_OPT_NUM) || (ip + cur + longestML >= iend)` (`:1294–1300`).
- **Cost of the price loop.** Because of these exits, the per-position loop over candidate lengths costs at most `sufficient_len` $< 2^{12}$ steps. `getAllMatches` makes at most $2^S$ compares. All but the last return a length $\le$ `ZSTD_OPT_NUM`; the last may return up to $\Lambda$, after which the loop breaks.
- **First block of `btultra2`.** `ZSTD_initStats_ultra` compresses it twice, a constant factor on one block.
- **Post-splitter (btopt and stronger).** `ZSTD_deriveBlockSplitsHelper` (`zstd_compress.c:4197`) bisects the sequence range of one block. It stops below `MIN_SEQUENCES_BLOCK_SPLITTING 300` sequences or at `ZSTD_MAX_NB_BLOCK_SPLITS 196` splits. Each level estimates the cost of its sub-range linearly, so the total is $O(\text{nbSeq}\cdot\log 196)$ per block.

**Lemma Z5 (entropy stage, per block of $\lambda$ bytes).**
- Literals use Huffman coding (Huffman 1952): histogram $O(\lambda+256)$, table construction over at most 256 symbols with `HUF_TABLELOG_MAX 12` (`lib/common/huf.h:37`), so $O(1)$ per block, then $O(1)$ per literal.
- Sequence codes use FSE/tANS (Duda 2013): table construction $O(2^{9})$ for LL/ML and $O(2^{8})$ for OF (`LLFSELog 9`, `MLFSELog 9`, `OffFSELog 8`, `zstd_internal.h:108–110`; RFC 8878 §3.1.1.3.2.1), then $O(1)$ per sequence.
- At most $\lambda$ literals and at most $\lambda/3$ sequences per block, so $O(\lambda)+O(1)$ per block.

**Other linear work.**
- Streaming copies each input byte once into the internal buffer.
- Index overflow correction (`ZSTD_reduceIndex`, `zstd_compress.c:2666`) costs $O(2^H+2^C)$ at most once every `ZSTD_CURRENT_MAX` $-\,2^W$ bytes, with `ZSTD_CURRENT_MAX` = 3500 MB on 64-bit (`zstd_compress_internal.h:1031`). That is $o(1)$ per byte.
- Creating the context initialises tables of $O(2^H+2^C)$ entries once. Call that constant $K_L$.

**Theorem Z (compression upper bound).** There is a constant $A_L$ (for any strategy, $A_L = O(2^S\Lambda)$; better per strategy below) such that, for every input of $n\ge1$ bytes,
$$T^{\rm zstd}_{\rm c}(x)\ \le\ A_L\,n + K_L\ \le\ (A_L+K_L)\cdot 3MN .$$

*Proof.*
- There are at most $n/2^{13}+1$ blocks (§3.1).
- Each block costs $O(1)$ in table builds and splitter overhead (Z5, Z4).
- Each byte is inserted at most once ($O(2^S\Lambda)$) and searched at most once ($O(2^S\Lambda)$) (Z2–Z4). Literals and sequences cost $O(1)$ each (Z5).
- Sum these and use $n\le 3MN$. ∎

**Sharper per-strategy bounds (amortized, rigorous).**
- **`ZSTD_fast` (level 1).** `zstd_fast.c:396–400`:
  ```
  mLength += ZSTD_count(ip0 + mLength, match0 + mLength, iend);
  ZSTD_storeSeq(...);
  ip0 += mLength;
  ```
  `ZSTD_count` runs only for the match that is then stored, and the parser skips the counted bytes. So count cost is at most $\#\text{seq}+n$. Each position does $O(1)$ hash work, and searchLog is not used. Therefore $A_1 = O(1)$, a small constant.
- **`ZSTD_dfast` (level 3).** `zstd_double_fast.c:256–294`. A short match is counted, then a long match at `ip1` (`l1len`). The longer one is kept, and then `ip += mLength`. The discarded count is at most as long as the kept one. Therefore $A_3=O(1)$.
- **`ZSTD_greedy` (depth 0).** Every search result with length $\ge4$ is the stored match. So a search costs $O(2^S(1+\ell^*))$, charged to the $\ell^*$ skipped bytes. Therefore $A = O(2^S)$.

### 3.3 Why "cost per byte grows like $2^S$" is a heuristic for lazy/lazy2/opt, not a theorem
For `lazy2` (level 9), a look-ahead chain may restart $k$ times. Each restart needs a strict gain increase: $4\ell-\mathrm{hb}(\text{off})$ grows by at least 5, or 8 at depth 2. With $H=\max\mathrm{hb}\le W+2$ this gives two facts:
- every candidate length in the chain is at most $\ell^*+H/4+O(1)$, so $\ell^* \ge \ell_{\max} - O(W)$, matching the outline;
- $k \le (4\ell^*+H)/5+O(1)$.

So one chain can cost $\Theta(2^S\,k\,\ell^*)$ while it consumes only about $k+\ell^*$ bytes, which is $O(2^S\min(k,\ell^*))$ per byte. This is bounded by $\Lambda$, not by a small constant. The repcode variants (`mlRep*3` vs `matchLength*3 - highbit + 1`, `:1635–1637`) move the gain by at most $O(W)$ per step and do not change this.

**What follows rigorously:**
- $A_L$ is a constant, so $\Theta(n)$ holds.
- $A_L=O(2^S)$ is proven only for fast, dfast and greedy.
- For lazy/lazy2 it holds when look-ahead chains have bounded length, which is the usual case.
- For btopt/btultra the per-byte constant is roughly $2^S\cdot2^{12}$ in the worst case.

**Measured speeds agree in direction:**
- level 1 (fast): about 157–199 MB/s;
- level 9 (lazy2, $S=4$): about 22 MB/s;
- level 19 (btultra2, $S=7$, `TL=256`, optimal parser): about 0.7 MB/s.

The $\sim\!250\times$ gap between level 1 and level 19 is larger than $2^7/2^1$. The price-based optimal parse adds the factor that searchLog alone does not explain.

### 3.4 Compression lower bound (any lossless compressor)
**Lemma LB.** Let $E$ be a deterministic encoder and $D$ a decoder with $D(E(x))=x$ for all $x$ in a domain $\mathcal X$. Let $x\in\mathcal X$, and let $i$ be a position such that changing $x_i$ to some value $b$ gives $x'\in\mathcal X$. Then $E$ reads position $i$ when run on $x$.

*Proof.* Suppose $E$ never reads $x_i$ on input $x$. Then $E$ runs identically on $x'$: the same reads return the same values. So $E(x)=E(x')$, and hence $D(E(x))=D(E(x'))$, which cannot equal both $x\ne x'$. ∎

- **For zstd**, $\mathcal X$ is all byte strings, so on *every* input all $n$ bytes are read. That is at least $n/8$ word reads, so $T^{\rm zstd}_{\rm c}\ge n/8\ge MN/8$ steps. This is the lower bound on every input, so the best case is $\Omega(MN)$ too.
- **Randomized encoders.** For a randomized encoder, apply the lemma for each fixed random string.
- **Larger words.** If $w$ grows with $n$ (transdichotomous, $w=\Theta(\log n)$), this argument gives only $\Omega(n/\log n)$ word reads. The $\Theta(MN)$ statements assume constant $w$ (§7).

### 3.5 Decompression: $\Theta(n)$
**Upper bound** (RFC 8878 §3.1.1; `lib/decompress/zstd_decompress_block.c`), per block:
- Raw and RLE blocks: $O(\text{Block\_Size})$.
- Compressed block, `ZSTD_decompressBlock_internal` (`:2066`):
  - `ZSTD_decodeLiteralsBlock` (`:134`): Huffman table $O(2^{11})$ (maximum code length 11 bits, RFC §4.2.1), then $O(1)$ per literal.
  - FSE tables via `ZSTD_buildFSETable` (`:626`): $O(2^9)$ each.
  - `ZSTD_decompressSequences_body` (`:1615`): the loop `for ( ; nbSeq ; nbSeq--)` (`:1659`) calls `ZSTD_decodeSequence`, $O(1)$, and then `ZSTD_execSequence` (`:1001`).
  - `ZSTD_execSequence` copies `litLength` literals and then `matchLength` bytes from `offset`. Copying is by wild copy, so it costs $O(1+\text{LL}+\text{ML})$.
- $\sum(\text{LL}+\text{ML})$ plus the last literals equals the block's output size.

So decoding costs $O(\#\text{blocks}) + O(n) = O(n)$. Blocks number at most $n/2^{13}+1$ for frames from this encoder (§3.1). On top of that is the $O(n)$ copy out of the 4 MiB buffer in `zstd_dec`/`sink`.

**Lower bound.** The decoder writes $n$ output bytes, at least $n/8$ word writes, so $\Omega(MN)$.

### 3.6 Space
- **Encoder:** $O(2^{W}+2^{H}+2^{C})$ bytes for the window buffer, hash table, chain/tree or row tables, plus optimal-parser state for btopt and stronger. These come from the level, not from $M$ or $N$, so $\Theta(1)$ in $M,N$.
- **Decoder:** $O(2^W)$ window plus $O(2^{17})$ block buffer plus tables, plus `zstd_dec`'s 4 MiB buffer. $\Theta(1)$.
- I did not compute exact byte counts; `ZSTD_estimateCStreamSize` and `ZSTD_estimateDStreamSize` would give them, and they were not run here.
- The memory-mapped input is not counted.

---

## 4. Algorithm 2: pack (`tries.c`)

$R$ is the number of rows per block, $\beta=\lceil M/R\rceil$ the number of blocks, $r_b\le R$ the rows of block $b$ ($\sum_b r_b=M$), and $n_b=\lceil r_b/8\rceil$ the number of 8-row tiles in block $b$.

### 4.1 Block size (`block_rows`)
```c
uint64_t r = g_R ? g_R : (BLOCK / d->cols) & ~7ull;
if (r > d->rows) r = (d->rows + 7) & ~7ull;
return r ? r : 8;
```
With $g_R=0$ this equals
$$R=\min\big(\mathrm{round8}(M),\ \max(8,\lfloor B/N\rfloor\,\&\,{\sim}7)\big),\qquad 8\le R .$$
This holds because $\mathrm{round8}(M)\ge 8$ for $M\ge1$, and $r\le M$ implies $r\le \mathrm{round8}(M)$.

Consequences:
$$\beta\le\lceil M/8\rceil\le \tfrac{M+7}{8}\le M,\qquad RN\le \max(B,8N)\le B+8N .$$

### 4.2 Encoder time: $\Theta(MN)$
**`scan`.** One `memchr` over the first line (at most $N+1$ steps), $O(1)$ arithmetic, then one EOL check per line (at most $2M$ steps). Total $T_{\rm scan}\le N+2M+O(1)$.

**`pack_enc`, per block $b$:**

| Step (code) | Steps |
|---|---|
| `memset(seen, 0, C * 256)` | $256N$ |
| mark seen: `seen[c*256 + base[r*stride + c]] = 1` | $r_bN$ |
| alphabet scan `for (v < 256)` plus `put` of $k_c$ bytes | $\le 256N+\sum_c k_c+O(N)\le 513N$ |
| 8-row tiles: per (tile, column), `x[8]` init, at most 8 cells × ($1+b_c$) bit operations, $b_c$ stores; $b_c\le 8$ | $\le 88\,n_bN\le 11r_bN+88N$ |
| `zw_write(w, o.p, o.n, 0)` | $\le Z_L\cdot o_b + z_0$ |

**Bytes sent to zstd per block.** Column $c$ has $k_c\le\min(256,r_b)$ distinct bytes and $b_c=\lceil\log_2k_c\rceil\le 8$, so
$$o_b=\sum_{c}\big(1+k_c+b_c n_b\big)\ \le\ N\big(1+r_b+(r_b+7)\big)=N(2r_b+8),$$
using $b_c n_b\le 8\lceil r_b/8\rceil\le r_b+7$. Summed over blocks:
$$S_z:=\sum_b o_b\le N(2M+8\beta)\le N(2M+M+7)\le 10\,MN,$$
plus a header of at most 32 bytes. By Theorem Z and its proof, zstd compresses $o$ bytes in at most $Z_L o + z_0$ steps per `zw_write` call, plus a one-time $K_L$.

**Theorem P-enc.** For all $M,N\ge1$:
$$MN\ \le\ T^{\rm pack}_{\rm c}(M,N)\ \le\ (12+2Z_L)MN + (857+8Z_L)N\beta + z_0\beta + N + 2M + K_L + O(1).$$

*Upper bound.* Add the table row by row over all blocks, using $\sum_b r_b=M$. Then apply $\beta\le M$, $N\ge1$ and $MN\ge1$:
$$T^{\rm pack}_{\rm c}\le (872+10Z_L+z_0+K_L+O(1))\cdot MN .$$
The user's form of the same step is $\beta\cdot256N\le 256N(M/R+1)\le 32MN+256N$, which uses $R\ge8$. When $R$ is capped by $M$, then $\beta=1$.

*Lower bound.* The marking loop alone executes $\sum_b r_bN=MN$ times. And by Lemma LB, *any* lossless encoder must read every cell:
- the valid-input domain is "fixed-width lines as accepted by `scan`";
- changing a cell byte to any value other than its own, `\n` or `\r` keeps the input valid, because `scan` checks only the first `\n` and the EOL positions;
- so $\Omega(MN)$ holds for every algorithm on every valid input. ∎

So $T^{\rm pack}_{\rm c}\in\hat\Theta(MN)$.

**The worst-case constant 857 is a corner case.** The term $N\beta$ costs $(857+8Z_L)/R$ per cell. With $N=76$, $R=55\,184$, that is below $0.02+Z_L/6900$ steps per cell. It reaches about $107+Z_L$ per cell only when $R=8$, which needs $N>B/8=524\,288$ pins.

### 4.3 Decoder time: $\Theta(MN)$
**`pack_dec`.**
- **Setup.** `alloc_rows` runs once: one allocation and at most $2R\le 2(M+7)\le16M$ EOL writes.
- **Per block:**
  - **Header.** The header loop reads $N$ bytes `k-1`, with $O(1)$ arithmetic each.
  - **Buffer refill.** `zr_fill` returns at once while enough bytes are buffered. The buffer holds a whole block (`cap = C*(257 + 8*((R+7)/8)) + 64`, which is at least $o_b$). After one refill (a `memmove` of fewer than $o_b$ bytes, then decoding until full) the rest of the block is present, so there is at most one refill per block. All `memmove`s together cost at most $S_z$ steps.
  - **zstd decoding.** Decoding the whole plane stream costs $O(S_z)$ by §3.5. The compressed size is at most `ZSTD_compressBound(S_z)` $=S_z+O(S_z/2^{17})+O(1)$.
  - **Tiles.** For each (tile, column) there are three cases:
    - $b_c=0$: at most 8 writes of `alpha[0]`;
    - $b_c=1$: at most 8 writes;
    - otherwise: $b_c$ plane reads plus at most $8(b_c+1)$ operations and the range check `v > ks[c]`.

    That is at most $80\,n_bN\le 10r_bN+80N$.
  - **Output.** `sink_rows` copies $r_b(N+e)\le3r_bN$ bytes.

**Theorem P-dec.** Let $D_L$ be zstd's per-byte decode constant, $d_0$ its per-call overhead and $K'_L$ the DCtx setup. For all $M,N\ge1$:
$$MN\ \le\ T^{\rm pack}_{\rm d}\ \le\ 13MN+81N\beta+(1+D_L)S_z+d_0\beta+16M+K'_L\ \le\ (120+10D_L+d_0+K'_L)\,MN .$$

*Upper bound.* The first inequality adds up the per-block items: tiles $10r_bN+80N$, sink $3r_bN$, header $N$, `memmove` plus decoding $(1+D_L)o_b$. The second uses $S_z\le N(2M+8\beta)$ and $\beta\le M$.

*Lower bound.* The tile loop writes every cell once. In addition, the $n$ output bytes give $\Omega(n)$ for any decoder.

So $T^{\rm pack}_{\rm d}\in\hat\Theta(MN)$ as in §4.2. ∎

### 4.4 Space (heap; mapped input and output file not counted)
**Encoder.**
- `seen` and `idx`: $256N$ bytes each. `bits`: $N$. `plane`: $8N$ (`size_t`). Together $521N$.
- `Buf o` (doubling `reserve`): capacity at most $4096+2\max_b o_b\le 4096+2N(264+R)\le 2B+544N+4096$.
- One zstd CCtx and `ZSTD_CStreamOutSize()` buffer: $\Theta(1)$.
- **Total:** $512N\le S^{\rm pack}_{\rm c}\le 2B+1065N+O(1)$, which is $\Theta(N)$ and independent of $M$, so pack streams in $M$.

**Decoder.**
- `z.buf`: $N(257+8\lceil R/8\rceil)+64\le B+272N+64$.
- `out`: $R(N+e)\le 3RN\le 3B+24N$.
- `bits`, `ks`, `at`: $10N$.
- One DCtx with window $2^{W_L}$: $\Theta(1)$.
- **Total:** $S^{\rm pack}_{\rm d}\le 4B+306N+O(1)$, and at least $N(257+8)$ for `z.buf`. That is $\Theta(N)$.

**Caveat.** $\Theta(N)$ hides an additive $2B$–$4B$ (8–16 MiB) that dominates until $N$ is in the thousands.

### 4.5 Constant-factor insight (not asymptotic)
Both methods are $\Theta(MN)$, so the measured speed-up is purely a constant: zstd's per-byte constant $Z_L$ multiplies $S_z$ instead of $n$.

- **0/1 columns.** For a block where every column has at most 2 symbols, $b_c\le1$ and $o_b\le N(\lceil r_b/8\rceil+3)$ per block, that is about $MN/8$ in total. That is up to 8× (LF) or $8(N+2)/N$× (CRLF) fewer bytes than $n$.
- **Constant columns.** Columns that are constant within a block have $b_c=0$ and contribute 2 bytes per block.
- **Zero-heavy planes.** Near-constant columns give planes that are almost all zero, which zstd processes quickly through long matches and repcodes.
- **Measured.** On 003–005, pack compresses 5.7–7.6× faster than zstd at the same level 9 (158/22, 166/29, 182/24 MB/s; `jobs/tests/ClaudeTries/CLAUDE.md`). This fits the 8× byte reduction minus pack's own $\approx 12+$ steps per cell.
- **Not measured.** $S_z$ for 003 was not measured. The 8× figure is the bound above, not a measurement.

---

## 5. little-o / little-omega consequences
Let $T$ be any of the four time functions. §3–§4 give $c_1MN\le T\le c_2MN$ for all $M,N\ge1$. Write $\min(M,N)\to\infty$ for Howell's "all variables $\ge N_0$".

1. **$T\in\hat o(g)$ whenever $MN/g(M,N)\to0$ as $\min(M,N)\to\infty$.** Given $c$, choose $N_0$ with $MN<(c/c_2)\,g$. Then $T<cg$, and $\hat T\le c_2MN<c\,g\le c\,\hat g$, which gives (5.1) and (5.2).
   - Examples: $MN\log(MN)$, $(MN)^{1+\varepsilon}$, $M^2N$, $MN^2$.
   - **Caveat:** $T\notin o(M^2N)$ along $M=1$, $N\to\infty$, because $T(1,N)\ge c_1N=c_1M^2N$. The claim holds only when both variables grow, which is exactly Howell's (and $O_\forall$'s) notion.
2. **$T\notin o(MN)$.** For $c<c_1$, $T<c\,MN$ fails at every point.
3. **$T\in\hat\omega(h)$ whenever $h$ is nondecreasing and $h/(MN)\to0$.** Then $\hat h=h$ and $\hat T\ge T\ge c_1MN>c\,h$.
   - Examples: $M+N$, $\sqrt{MN}$, $MN/\log_2(MN+1)$ (nondecreasing for $MN\ge1$), and any constant.
   - **Caveat:** along $N=1$, $(M+N)/(MN)\to1$. So "$\omega(M+N)$" needs both variables to grow.
4. **$T\notin\omega(MN)$.** For $c>c_2$, $T>c\,MN$ fails everywhere.
5. **Per variable.** For fixed $N_0$: $c_1N_0\,M\le T(M,N_0)\le c_2N_0\,M$, so $T(\cdot,N_0)\in\Theta(M)$, $o(M\log M)$ and $\omega(M/\log M)$. Symmetrically, for fixed $M_0$, $T(M_0,\cdot)\in\Theta(N)$.
6. **Best = worst = average.** The lower bound holds on every input, so all three are $\Theta(MN)$. Only $c_1\le c(x)\le c_2$ varies with content, for example literal-heavy versus match-heavy data for zstd, or $b_c$ for pack.
7. **Space.** zstd: $\Theta(1)$, so it is in $o(g)$ for every $g\to\infty$. pack: $\Theta(N)$, so it is in $\hat o(MN)$, $\hat\omega(1)$ and $\hat\omega(\log N)$, and is $\Theta(1)$ in $M$ for fixed $N$.

---

## 6. Empirical cross-check (our measurement)
**Setup.** Prefixes of file 003 ($N=76$, LF), single thread, decoder output discarded. Source: `jobs/tests/ClaudeTries/CLAUDE.md`, "Scaling" table, 2026-11-10.

| size | pack L1 compr / decomp MB/s | zstd L9 compr / decomp MB/s |
|---|---|---|
| 25 MB | 147 / 545 | 13 / 396 |
| 100 MB | 141 / 483 | 18 / 553 |
| 400 MB | 175 / 613 | 19 / 454 |
| 1.6 GB | 180 / 616 | 21 / 518 |
| 2.5 GB | 161 / 581 | 22 / 566 |

**Reading.**
- The size grows 100×, but MB/s does not fall. pack stays within about ±12%, and zstd L9 rises slightly from 13 to 22 MB/s.
- Super-linear time in $M$ would show MB/s falling, so this is consistent with $\Theta(M)$ at fixed $N$.
- All runs round-tripped byte-exact (SHA-256 / `cmp`, same file).

**Limits of this check.**
- These are single runs of wall-clock time, with no repetitions or confidence intervals.
- **$N$-scaling is not tested.** The corpus has only a few widths (002: $N=5$; 003: $N=76$; the other files have other fixed widths), and no controlled sweep over $N$ was run. The constant-factor effect of small $N$ shows up as 002 decoding at about 500 MB/s against zstd's 1080. The 8-row tile loop has per-(tile, column) overhead that 5 pins cannot amortize. This is a constant, not an order, effect.
- Speed at $N>B/8$ (where $R=8$) is untested.

---

## 7. Limits and assumptions
- **Fixed constants.** The zstd level $L$ (hence $W,C,H,S$, strategy) and pack's $B$ are constants. If $L$ or $B$ were inputs, the bounds would carry them: for example $2^S$, $2^W$ space, $B$ space, and the $256N\beta$ term.
- **Machine model.** Word-RAM with constant $w=64$. In a transdichotomous model the reading lower bound weakens to $\Omega(n/w)$ (§3.4).
- **I/O.** Disk I/O and page-fault/mmap costs are excluded. `fwrite`/`fread` are counted only as byte copies. The file-to-file speeds in `CLAUDE.md` (84–288 MB/s decode) are limited by disk, not covered by this model.
- **The zstd constants are not proofs from its authors.** They are derived from the cited v1.5.7 functions. The worst-case per-byte constant ($O(2^S\Lambda)$ for lazy and bt strategies) is very loose. The $O(2^S)$ amortized form is proven only for fast, dfast and greedy (§3.3). Not analysed: `btlazy2` (levels 13–15, `ZSTD_DUBT_findBestMatch`), LDM (`-long`), dictionaries and multithreading. They are not used in the measured configurations.
- **Decoder input.** Decoder bounds are for streams produced by the encoder. Malformed or adversarial streams are not analysed. pack's decoder does reject `R > 2^30` and `N > 2^24` (`pack_dec`), so **its analysis holds for $N\le 2^{24}$**.
- **Valid input only.** pack accepts only fixed-width input (`scan`); anything else is an error, with no fallback in `tries.c`. zstd accepts any bytes.
- **Correctness.** Losslessness is verified empirically (SHA-256 / `cmp`) and is not proven here. This note covers complexity only.
- **Constant-time cases.** Tiny inputs (001, 20 KB) are dominated by the context setup constant $K_L$ (table initialisation), which is why MB/s is "tiny" there. This is compatible with $T\le c\,MN$ because $MN\ge1$, but it means $c_2$ is large.

---

## 8. References
1. Collet, Y.; Kucherawy, M. (Ed.). *Zstandard Compression and the 'application/zstd' Media Type.* RFC 8878, IETF, February 2021. Checked: §3.1.1.2.4 Block_Maximum_Size, §3.1.1.3.2.1 maximum accuracy logs 9/9/8, §3.1.1.4 sequence execution, §4.2.1 maximum Huffman code length 11.
2. Meta Platforms. *Zstandard*, source code, tag v1.5.7, https://github.com/facebook/zstd. Files read: `lib/compress/{clevels.h, zstd_compress.c, zstd_compress_internal.h, zstd_lazy.c, zstd_opt.c, zstd_fast.c, zstd_double_fast.c, zstd_preSplit.c}`, `lib/common/{zstd_internal.h, huf.h}`, `lib/decompress/zstd_decompress_block.c`, `lib/zstd.h`.
3. Ziv, J.; Lempel, A. "A universal algorithm for sequential data compression." *IEEE Trans. Inf. Theory* 23(3):337–343, 1977. This is LZ77, the parsing model behind zstd's match/literal sequences. Its bounded-window, bounded-candidate variant is what makes zstd linear.
4. Huffman, D. A. "A method for the construction of minimum-redundancy codes." *Proc. IRE* 40(9):1098–1101, 1952.
5. Duda, J. "Asymmetric numeral systems: entropy coding combining speed of Huffman coding with compression rate of arithmetic coding." arXiv:1311.2540, 2013 (v2 January 2014). Checked on arXiv.
6. Cormen, T. H.; Leiserson, C. E.; Rivest, R. L.; Stein, C. *Introduction to Algorithms*, 3rd ed., MIT Press, 2009, ch. 3 "Growth of Functions".
7. Knuth, D. E. "Big Omicron and big Omega and big Theta." *SIGACT News* 8(2):18–24, 1976. Volume and pages were checked against Howell's bibliography; the issue number (2) is the standard citation and was not checked against the original.
8. Howell, R. R. *On Asymptotic Notation with Multiple Variables.* Tech. Rep. 2007-4, Dept. of Computing and Information Sciences, Kansas State University, January 18, 2008. Definitions (3.1)–(5.4) were checked against the PDF text (people.cs.ksu.edu/~rhowell/asymptotic.pdf).
9. Our measurements: `jobs/tests/ClaudeTries/CLAUDE.md` (full-corpus and scaling tables, 2026-11-10). Implementation: `jobs/tests/ClaudeTries/tries.c` (`scan`, `block_rows`, `pack_enc`, `pack_dec`, `alloc_rows`, `zr_fill`, `zstd_enc`, `zstd_dec`).
