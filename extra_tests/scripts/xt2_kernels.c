/*
 * extra_tests round 2 -- "block-indexed split-stream zstd container" (bk).
 * Standalone: shares no code with patzstd/, patamd/ or round-1 xt_kernels.c.
 *
 * Encoder (E1-E8 of the research report):
 *   - grid scan, per-pin alphabet -> 1 or 2 bit planes per pin (code 0 = first-row symbol)
 *   - rows cut into blocks of R vectors (R multiple of 8; R >= rows -> one block)
 *   - per block and per plane: ZERO / ONES / COPY(q) / NOT(q) / STORED / STORED_X
 *     (STORED_X = bit transitions along time, chosen per plane by a zstd-1 trial)
 *   - stored planes of a block -> ONE zstd frame (level L, optional LDM with the
 *     window sized to the block stream); blocks compressed in parallel (OpenMP)
 * Decoder (D1-D6):
 *   - serial parse of the tiny block index, then blocks decoded in parallel:
 *     ZSTD_decompressDCtx into a per-thread scratch reused across blocks,
 *     planes resolved by pointer (no copies for COPY / ZERO / ONES),
 *     rows written straight to their final offset (fixed-width rows).
 *
 * Also: row hashes for the profiler.
 * Build: gcc -O3 -march=native -fopenmp -shared -fPIC xt2_kernels.c -lzstd -o libxt2.so
 */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <omp.h>
#include <zstd.h>

#define MAXW 4096
enum { K_ZERO = 0, K_ONES = 1, K_COPY = 2, K_NOT = 3, K_STORED = 4, K_STORED_X = 5 };

/* ------------------------------------------------------------------ scan */
int64_t xt2_scan(const uint8_t *buf, int64_t n, int W, uint8_t *present, int nth)
{
    if (W <= 0 || W > MAXW || n % (W + 1)) return -1;
    int64_t rows = n / (W + 1);
    int bad = 0;
    memset(present, 0, (size_t)W * 256);
    #pragma omp parallel num_threads(nth) reduction(|:bad)
    {
        uint8_t *loc = calloc((size_t)W * 256, 1);
        #pragma omp for schedule(static)
        for (int64_t r = 0; r < rows; r++) {
            const uint8_t *s = buf + r * (W + 1);
            if (s[W] != '\n') bad = 1;
            for (int p = 0; p < W; p++) loc[p * 256 + s[p]] = 1;
        }
        #pragma omp critical
        for (int i = 0; i < W * 256; i++) present[i] |= loc[i];
        free(loc);
    }
    return bad ? -1 : rows;
}

/* ------------------------------------------------------------- profiler */
static inline uint64_t mix(uint64_t h, uint64_t v)
{
    h ^= v * 0x9E3779B97F4A7C15ULL;
    h = (h << 27) | (h >> 37);
    return h * 0xC2B2AE3D27D4EB4FULL + 0x165667B19E3779F9ULL;
}

void xt2_row_hash(const uint8_t *buf, int64_t rows, int W, uint64_t *out, int nth)
{
    #pragma omp parallel for num_threads(nth) schedule(static)
    for (int64_t r = 0; r < rows; r++) {
        const uint8_t *s = buf + r * (W + 1);
        uint64_t h = (uint64_t)W;
        int p = 0;
        for (; p + 8 <= W; p += 8) { uint64_t v; memcpy(&v, s + p, 8); h = mix(h, v); }
        uint64_t v = 0;
        memcpy(&v, s + p, W - p);
        out[r] = mix(h, v);
    }
}

/* exact count of rows identical to the previous row */
int64_t xt2_eq_prev(const uint8_t *buf, int64_t rows, int W, int nth)
{
    int64_t c = 0;
    #pragma omp parallel for num_threads(nth) reduction(+:c) schedule(static)
    for (int64_t r = 1; r < rows; r++)
        c += !memcmp(buf + r * (W + 1), buf + (r - 1) * (W + 1), W);
    return c;
}

/* ---------------------------------------------------------- bit helpers */
static inline void trans_fwd(uint8_t *x, int64_t n)
{
    uint8_t prev = 0;
    for (int64_t i = 0; i < n; i++) {
        uint8_t v = x[i];
        x[i] = (uint8_t)(v ^ ((v >> 1) | (uint8_t)(prev << 7)));
        prev = v & 1;
    }
}

static inline void trans_inv(uint8_t *x, int64_t n)
{
    uint8_t carry = 0;
    for (int64_t i = 0; i < n; i++) {
        uint8_t v = x[i];
        v ^= v >> 1; v ^= v >> 2; v ^= v >> 4;
        if (carry) v ^= 0xFF;
        x[i] = v;
        carry = v & 1;
    }
}

static uint64_t hash_bytes(const uint8_t *p, int64_t n, int invert, uint8_t lastmask)
{
    uint64_t h = 0x12345;
    int64_t i = 0;
    uint64_t inv = invert ? ~0ULL : 0;
    for (; i + 8 <= n - 1; i += 8) { uint64_t v; memcpy(&v, p + i, 8); h = mix(h, v ^ inv); }
    for (; i < n - 1; i++) h = mix(h, (uint8_t)(p[i] ^ (uint8_t)inv));
    if (n) h = mix(h, (uint8_t)((p[n - 1] ^ (uint8_t)inv) & lastmask));
    return h;
}

/* ------------------------------------------------------------- planes */
/* Plane layout during encode: block b at base[b], plane k at base[b] + k*bb[b]. */
typedef struct {
    int W, nplanes;
    int pin_k0[MAXW], pin_k1[MAXW];       /* plane index of a pin's bit 0 / bit 1, -1 none */
    int plane_pin[2 * MAXW], plane_bit[2 * MAXW];
} layout_t;

static void make_layout(layout_t *L, int W, const int32_t *nb)
{
    int k = 0;
    L->W = W;
    for (int p = 0; p < W; p++) {
        L->pin_k0[p] = L->pin_k1[p] = -1;
        if (nb[p] >= 1) { L->pin_k0[p] = k; L->plane_pin[k] = p; L->plane_bit[k] = 0; k++; }
        if (nb[p] == 2) { L->pin_k1[p] = k; L->plane_pin[k] = p; L->plane_bit[k] = 1; k++; }
    }
    L->nplanes = k;
}

static void pack_all(const uint8_t *buf, int64_t rows, const layout_t *L, const uint8_t *lut,
                     int64_t R, uint8_t *planes, int nth)
{
    int W = L->W, np = L->nplanes;
    int64_t ngroups = (rows + 7) / 8, Rg = R / 8;
    int64_t bbfull = Rg;                               /* bytes per plane in a full block */
    #pragma omp parallel num_threads(nth)
    {
        uint8_t a0[MAXW], a1[MAXW];
        #pragma omp for schedule(static, 4096)
        for (int64_t g = 0; g < ngroups; g++) {
            int64_t b = g / Rg, gb = g - b * Rg;
            int64_t r0 = b * R, rb = rows - r0 < R ? rows - r0 : R;
            int64_t bb = (rb + 7) / 8;
            uint8_t *base = planes + b * bbfull * np;
            memset(a0, 0, W); memset(a1, 0, W);
            for (int r = 0; r < 8; r++) {
                int64_t row = g * 8 + r;
                if (row < rows) {
                    const uint8_t *s = buf + row * (W + 1);
                    for (int p = 0; p < W; p++) {
                        uint8_t c = lut[p * 256 + s[p]];
                        a0[p] = (uint8_t)((a0[p] << 1) | (c & 1));
                        a1[p] = (uint8_t)((a1[p] << 1) | (c >> 1));
                    }
                } else {
                    for (int p = 0; p < W; p++) { a0[p] <<= 1; a1[p] <<= 1; }
                }
            }
            for (int p = 0; p < W; p++) {
                if (L->pin_k0[p] >= 0) base[L->pin_k0[p] * bb + gb] = a0[p];
                if (L->pin_k1[p] >= 0) base[L->pin_k1[p] * bb + gb] = a1[p];
            }
        }
    }
}

/* --------------------------------------------------------------- encode */
/* Block index entry (written to meta, per block):
 *   u64 csize, u32 nstored, then per plane: u8 kind [, u16 ref for COPY/NOT]   */
typedef struct {
    uint8_t *frame; int64_t csize;
    uint8_t *meta;  int64_t mlen;
} blk_t;

/* optional zstd parameter overrides for the block frames (0 = level default):
 * minMatch, targetLength, searchLog, strategy, chainLog, hashLog */
static int g_par[6];
static int g_groups = 1;          /* frames per block, set by xt2_encode */
void xt2_set_params(int mm, int tl, int sl, int st, int cl, int hl)
{
    g_par[0] = mm; g_par[1] = tl; g_par[2] = sl; g_par[3] = st; g_par[4] = cl; g_par[5] = hl;
}

static int64_t zcompress(ZSTD_CCtx *c, const uint8_t *src, int64_t n, uint8_t *dst, int64_t cap,
                         int level, int lng, int workers)
{
    ZSTD_CCtx_reset(c, ZSTD_reset_session_and_parameters);
    ZSTD_CCtx_setParameter(c, ZSTD_c_compressionLevel, level);
    if (g_par[0]) ZSTD_CCtx_setParameter(c, ZSTD_c_minMatch, g_par[0]);
    if (g_par[1]) ZSTD_CCtx_setParameter(c, ZSTD_c_targetLength, g_par[1]);
    if (g_par[2]) ZSTD_CCtx_setParameter(c, ZSTD_c_searchLog, g_par[2]);
    if (g_par[3]) ZSTD_CCtx_setParameter(c, ZSTD_c_strategy, g_par[3]);
    if (g_par[4]) ZSTD_CCtx_setParameter(c, ZSTD_c_chainLog, g_par[4]);
    if (g_par[5]) ZSTD_CCtx_setParameter(c, ZSTD_c_hashLog, g_par[5]);
    if (lng) {
        int wl = 10;
        while (wl < 31 && ((int64_t)1 << wl) < n) wl++;
        ZSTD_CCtx_setParameter(c, ZSTD_c_windowLog, wl);
        ZSTD_CCtx_setParameter(c, ZSTD_c_enableLongDistanceMatching, 1);
    }
    if (workers) ZSTD_CCtx_setParameter(c, ZSTD_c_nbWorkers, workers);
    ZSTD_CCtx_setPledgedSrcSize(c, (unsigned long long)n);
    size_t r = ZSTD_compress2(c, dst, cap, src, n);
    return ZSTD_isError(r) ? -1 : (int64_t)r;
}

static int encode_block(ZSTD_CCtx *c, uint8_t *P, int64_t rb, const layout_t *L, int level, int lng,
                        int autox, int workers, int xpar, blk_t *out, int64_t *stat,
                        const uint8_t *pre, int64_t prelen)
{
    int np = L->nplanes;
    int64_t bb = (rb + 7) / 8;
    int v = (int)(rb % 8);
    uint8_t lastmask = v ? (uint8_t)(0xFF << (8 - v)) : 0xFF;
    uint8_t *kind = malloc(np), *xf = calloc(np, 1);
    uint16_t *ref = malloc(np * sizeof(uint16_t));
    uint64_t *h = malloc(np * sizeof(uint64_t));
    int nst = 0;
    for (int k = 0; k < np; k++) {
        uint8_t *x = P + k * bb;
        int z = 1, o = 1;
        for (int64_t i = 0; i < bb - 1 && (z || o); i++) { z &= x[i] == 0; o &= x[i] == 0xFF; }
        if (bb) { z &= (x[bb - 1] & lastmask) == 0; o &= (x[bb - 1] & lastmask) == lastmask; }
        if (z) { kind[k] = K_ZERO; stat[0]++; continue; }
        if (o) { kind[k] = K_ONES; stat[1]++; continue; }
        h[k] = hash_bytes(x, bb, 0, lastmask);
        uint64_t hc = hash_bytes(x, bb, 1, lastmask);
        kind[k] = K_STORED;
        for (int q = 0; q < k; q++) {
            if (kind[q] != K_STORED) continue;
            uint8_t *y = P + q * bb;
            if (h[q] == h[k] && !memcmp(x, y, bb)) { kind[k] = K_COPY; ref[k] = q; stat[2]++; break; }
            if (h[q] == hc) {
                int eq = 1;
                for (int64_t i = 0; i < bb - 1 && eq; i++) eq = x[i] == (uint8_t)~y[i];
                if (eq && bb) eq = (x[bb - 1] & lastmask) == ((uint8_t)~y[bb - 1] & lastmask);
                if (eq) { kind[k] = K_NOT; ref[k] = q; stat[3]++; break; }
            }
        }
        if (kind[k] == K_STORED) { nst++; stat[4]++; }
    }
    /* build the stored stream (copy), optional per-plane transition trial */
    int64_t slen = (int64_t)nst * bb + prelen;
    uint8_t *S0 = malloc(slen ? slen : 1), *S = S0 + prelen;
    if (prelen) memcpy(S0, pre, prelen);
    int *sk = malloc(np * sizeof(int)), ns = 0;
    for (int k = 0; k < np; k++) if (kind[k] == K_STORED) sk[ns++] = k;
    #pragma omp parallel for num_threads(xpar) schedule(dynamic, 1)
    for (int s = 0; s < ns; s++) {
        uint8_t *dst = S + (int64_t)s * bb;
        memcpy(dst, P + sk[s] * bb, bb);
        if (autox && bb >= 4096) {
            ZSTD_CCtx *t = ZSTD_createCCtx();
            size_t cap = ZSTD_compressBound(bb);
            uint8_t *tmp = malloc(cap), *alt = malloc(bb);
            memcpy(alt, dst, bb);
            trans_fwd(alt, bb);
            size_t a = ZSTD_compressCCtx(t, tmp, cap, dst, bb, 1);
            size_t b = ZSTD_compressCCtx(t, tmp, cap, alt, bb, 1);
            if (!ZSTD_isError(a) && !ZSTD_isError(b) && b * 100 < a * 97) {   /* >3% better */
                memcpy(dst, alt, bb); xf[sk[s]] = 1;
            }
            free(tmp); free(alt); ZSTD_freeCCtx(t);
        }
    }
    for (int s = 0; s < ns; s++) if (xf[sk[s]]) { kind[sk[s]] = K_STORED_X; stat[5]++; }
    /* compress: G frames cut at plane boundaries (frame 0 also holds the prefix),
     * compressed in parallel by this block's xpar threads */
    int G = g_groups > 0 ? g_groups : 1;
    if (G > nst) G = nst > 0 ? nst : 1;
    int64_t maxg = slen / (1 << 20);
    if (maxg < 1) maxg = 1;
    if (G > maxg) G = (int)maxg;
    int64_t per = nst ? ((int64_t)nst + G - 1) / G : 0;
    if (per) G = (int)(((int64_t)nst + per - 1) / per);
    int64_t *fs = malloc((G + 1) * sizeof(int64_t)), *fc = malloc(G * sizeof(int64_t));
    uint8_t **fb = malloc(G * sizeof(uint8_t *));
    for (int j = 0; j < G; j++) fs[j] = j ? prelen + j * per * bb : 0;
    fs[G] = slen;
    int ferr = 0;
    if (G == 1) {
        int64_t cap = ZSTD_compressBound(slen);
        fb[0] = malloc(cap ? cap : 1);
        fc[0] = slen ? zcompress(c, S0, slen, fb[0], cap, level, lng, workers) : 0;
        if (fc[0] < 0) ferr = 1;
    } else {
        #pragma omp parallel num_threads(xpar) reduction(|:ferr)
        {
            ZSTD_CCtx *t = ZSTD_createCCtx();
            #pragma omp for schedule(dynamic, 1)
            for (int j = 0; j < G; j++) {
                int64_t len = fs[j + 1] - fs[j], cap = ZSTD_compressBound(len);
                fb[j] = malloc(cap ? cap : 1);
                fc[j] = len ? zcompress(t, S0 + fs[j], len, fb[j], cap, level, lng, 0) : 0;
                if (fc[j] < 0) ferr = 1;
            }
            ZSTD_freeCCtx(t);
        }
    }
    free(S0); free(sk);
    if (ferr) return -1;
    out->csize = 0;
    for (int j = 0; j < G; j++) out->csize += fc[j];
    out->frame = malloc(out->csize ? out->csize : 1);
    for (int64_t j = 0, o = 0; j < G; j++) { memcpy(out->frame + o, fb[j], fc[j]); o += fc[j]; free(fb[j]); }
    out->meta = malloc(22 + 8 * (int64_t)G + 3 * (int64_t)np);
    uint8_t *m = out->meta;
    memcpy(m, &out->csize, 8); m += 8;
    uint32_t n32 = nst; memcpy(m, &n32, 4); m += 4;
    n32 = (uint32_t)rb; memcpy(m, &n32, 4); m += 4;      /* rows actually packed */
    n32 = (uint32_t)per; memcpy(m, &n32, 4); m += 4;     /* stored planes per frame */
    uint16_t g16 = (uint16_t)G; memcpy(m, &g16, 2); m += 2;
    for (int j = 0; j < G; j++) { memcpy(m, &fc[j], 8); m += 8; }
    free(fs); free(fc); free(fb);
    for (int k = 0; k < np; k++) {
        *m++ = kind[k];
        if (kind[k] == K_COPY || kind[k] == K_NOT) { memcpy(m, &ref[k], 2); m += 2; }
    }
    out->mlen = m - out->meta;
    free(kind); free(xf); free(ref); free(h);
    return 0;
}

/* pack only the rows listed in idx (repeat mode); planes k at P + k*bb */
static void pack_idx(const uint8_t *buf, const int64_t *idx, int64_t nk, const layout_t *L,
                     const uint8_t *lut, uint8_t *P, int nth)
{
    int W = L->W;
    int64_t bb = (nk + 7) / 8;
    #pragma omp parallel num_threads(nth)
    {
        uint8_t a0[MAXW], a1[MAXW];
        #pragma omp for schedule(static, 2048)
        for (int64_t g = 0; g < bb; g++) {
            memset(a0, 0, W); memset(a1, 0, W);
            for (int r = 0; r < 8; r++) {
                int64_t j = g * 8 + r;
                if (j < nk) {
                    const uint8_t *s = buf + idx[j] * (W + 1);
                    for (int p = 0; p < W; p++) {
                        uint8_t c = lut[p * 256 + s[p]];
                        a0[p] = (uint8_t)((a0[p] << 1) | (c & 1));
                        a1[p] = (uint8_t)((a1[p] << 1) | (c >> 1));
                    }
                } else {
                    for (int p = 0; p < W; p++) { a0[p] <<= 1; a1[p] <<= 1; }
                }
            }
            for (int p = 0; p < W; p++) {
                if (L->pin_k0[p] >= 0) P[L->pin_k0[p] * bb + g] = a0[p];
                if (L->pin_k1[p] >= 0) P[L->pin_k1[p] * bb + g] = a1[p];
            }
        }
    }
}

/* repeat-mode block: drop rows equal to the previous row of the same block,
 * prefix the frame with the repeat bitmap (ceil(rb/8) bytes) when any row was dropped */
static int encode_block_rr(ZSTD_CCtx *c, const uint8_t *buf, int64_t r0, int64_t rb, const layout_t *L,
                           const uint8_t *lut, int level, int lng, int autox, int workers, int xpar,
                           blk_t *out, int64_t *stat)
{
    int W = L->W;
    int64_t bbr = (rb + 7) / 8, nk = 0;
    uint8_t *rep = calloc(bbr + 1, 1);
    int64_t *idx = malloc(rb * sizeof(int64_t));
    for (int64_t i = 0; i < rb; i++) {
        const uint8_t *s = buf + (r0 + i) * (W + 1);
        if (i && !memcmp(s, s - (W + 1), W)) rep[i >> 3] |= (uint8_t)(0x80 >> (i & 7));
        else idx[nk++] = r0 + i;
    }
    int64_t bb = (nk + 7) / 8;
    uint8_t *P = calloc((size_t)L->nplanes * bb + 1, 1);
    pack_idx(buf, idx, nk, L, lut, P, xpar);
    int e = encode_block(c, P, nk, L, level, lng, autox, workers, xpar, out, stat,
                         rep, nk < rb ? bbr : 0);
    free(P); free(idx); free(rep);
    return e;
}

/* Returns total frame bytes in *dst (malloc'd, caller frees with xt2_free),
 * block index in *meta. stat[6]: zero, ones, copy, not, stored, stored_x. */
int64_t xt2_encode(const uint8_t *buf, int64_t rows, int W, const uint8_t *lut, const int32_t *nb,
                   int64_t R, int level, int lng, int autox, int rr, int grp, int nth,
                   uint8_t **dst, uint8_t **meta, int64_t *meta_len, int64_t *stat)
{
    layout_t *L = malloc(sizeof(layout_t));
    make_layout(L, W, nb);
    if (R >= rows) R = (rows + 7) / 8 * 8;
    if (R < 8) R = 8;
    int64_t nblk = (rows + R - 1) / R;
    int np = L->nplanes;
    uint8_t *planes = rr ? NULL : calloc((size_t)nblk * (R / 8) * np + 1, 1);
    if (!rr) pack_all(buf, rows, L, lut, R, planes, nth);
    blk_t *B = calloc(nblk, sizeof(blk_t));
    int err = 0;
    int64_t st[6] = {0};
    /* two-level parallelism: blocks across `outer` threads, frames of a block
     * (pin groups) across `inner` threads -> every core busy even with 1 block */
    int outer = nblk < nth ? (int)nblk : nth, inner = nth / outer;
    if (inner < 1) inner = 1;
    g_groups = grp ? 2 * inner : 1;
    omp_set_max_active_levels(2);
    #pragma omp parallel num_threads(outer) reduction(|:err)
    {
        ZSTD_CCtx *c = ZSTD_createCCtx();
        int64_t ls[6] = {0};
        int wk = (!grp && inner > 1) ? inner : 0;
        #pragma omp for schedule(dynamic, 1)
        for (int64_t b = 0; b < nblk; b++) {
            int64_t rb = rows - b * R < R ? rows - b * R : R;
            int e = rr ? encode_block_rr(c, buf, b * R, rb, L, lut, level, lng, autox, wk, inner, &B[b], ls)
                       : encode_block(c, planes + b * (R / 8) * np, rb, L, level, lng, autox, wk, inner,
                                      &B[b], ls, NULL, 0);
            if (e) err = 1;
        }
        #pragma omp critical
        for (int i = 0; i < 6; i++) st[i] += ls[i];
        ZSTD_freeCCtx(c);
    }
    free(planes);
    int64_t tot = 0, mt = 8;
    for (int64_t b = 0; b < nblk; b++) { tot += B[b].csize; mt += B[b].mlen; }
    *dst = malloc(tot ? tot : 1);
    *meta = malloc(mt);
    memcpy(*meta, &R, 8);
    int64_t pos = 0, mp = 8;
    for (int64_t b = 0; b < nblk; b++) {
        memcpy(*dst + pos, B[b].frame, B[b].csize); pos += B[b].csize;
        memcpy(*meta + mp, B[b].meta, B[b].mlen); mp += B[b].mlen;
        free(B[b].frame); free(B[b].meta);
    }
    *meta_len = mt;
    memcpy(stat, st, sizeof st);
    free(B); free(L);
    return err ? -1 : tot;
}

void xt2_free(void *p) { free(p); }

/* --------------------------------------------------------------- decode */
static void unpack_block(uint8_t **PP, int64_t rb, const layout_t *L, const uint8_t *sym,
                         uint8_t *out, int nth)
{
    int W = L->W;
    int64_t bb = (rb + 7) / 8;
    uint8_t S0[MAXW], S1[MAXW], S2[MAXW], S3[MAXW];
    for (int p = 0; p < W; p++) {
        S0[p] = sym[p * 4]; S1[p] = sym[p * 4 + 1]; S2[p] = sym[p * 4 + 2]; S3[p] = sym[p * 4 + 3];
    }
    #pragma omp parallel num_threads(nth)
    {
        uint8_t a0[MAXW], a1[MAXW];
        #pragma omp for schedule(static, 2048)
        for (int64_t g = 0; g < bb; g++) {
            for (int p = 0; p < W; p++) {
                a0[p] = L->pin_k0[p] >= 0 ? PP[L->pin_k0[p]][g] : 0;
                a1[p] = L->pin_k1[p] >= 0 ? PP[L->pin_k1[p]][g] : 0;
            }
            for (int r = 0; r < 8; r++) {
                int64_t row = g * 8 + r;
                if (row >= rb) break;
                uint8_t *d = out + row * (W + 1);
                int sh = 7 - r;
                for (int p = 0; p < W; p++) {
                    uint8_t b0 = (a0[p] >> sh) & 1, b1 = (a1[p] >> sh) & 1;
                    uint8_t lo = b0 ? S1[p] : S0[p], hi = b0 ? S3[p] : S2[p];
                    d[p] = b1 ? hi : lo;
                }
                d[W] = '\n';
            }
        }
    }
}

typedef struct { int64_t foff, csize, moff, hlen; uint32_t nst, nk, per; uint16_t nfr; } dblk_t;

static int decode_block(ZSTD_DCtx *d, const uint8_t *src, const dblk_t *e, const uint8_t *meta,
                        int64_t rb, const layout_t *L, const uint8_t *sym, uint8_t *out,
                        uint8_t **scratch, int64_t *scap, int nth)
{
    int np = L->nplanes, W = L->W;
    int64_t rfull = rb, bbr = (rb + 7) / 8, pre = e->nk < rb ? bbr : 0;
    rb = e->nk;
    int64_t bb = (rb + 7) / 8;
    int nnot = 0;
    const uint8_t *m = meta + e->moff + e->hlen;
    for (int k = 0; k < np; k++) { uint8_t t = *m++; if (t == K_COPY || t == K_NOT) { m += 2; nnot += t == K_NOT; } }
    int64_t need = ((int64_t)e->nst + nnot + 2) * bb + pre + 1;
    if (need > *scap) { free(*scratch); *scratch = malloc(need); *scap = need; }
    uint8_t *Rp = *scratch, *S = *scratch + pre, *Z = S + (int64_t)(e->nst + nnot) * bb, *O = Z + bb, *N = S + (int64_t)e->nst * bb;
    memset(Z, 0, bb); memset(O, 0xFF, bb);
    if (e->nst || pre) {
        int64_t want = (int64_t)e->nst * bb + pre;
        int G = e->nfr, ferr = 0;
        const uint8_t *cs = meta + e->moff + 22;
        if (G == 1) {
            size_t r = ZSTD_decompressDCtx(d, Rp, (size_t)want, src + e->foff, e->csize);
            if (ZSTD_isError(r) || (int64_t)r != want) return -1;
        } else {
            int64_t *co = malloc((G + 1) * sizeof(int64_t));
            co[0] = 0;
            for (int j = 0; j < G; j++) { int64_t c; memcpy(&c, cs + 8 * j, 8); co[j + 1] = co[j] + c; }
            #pragma omp parallel num_threads(nth) reduction(|:ferr)
            {
                ZSTD_DCtx *t = ZSTD_createDCtx();
                ZSTD_DCtx_setParameter(t, ZSTD_d_windowLogMax, 31);
                #pragma omp for schedule(dynamic, 1)
                for (int j = 0; j < G; j++) {
                    int64_t s0 = j ? pre + (int64_t)j * e->per * bb : 0;
                    int64_t s1 = j + 1 < G ? pre + (int64_t)(j + 1) * e->per * bb : want;
                    size_t r = ZSTD_decompressDCtx(t, Rp + s0, s1 - s0, src + e->foff + co[j], co[j + 1] - co[j]);
                    if (ZSTD_isError(r) || (int64_t)r != s1 - s0) ferr = 1;
                }
                ZSTD_freeDCtx(t);
            }
            free(co);
            if (ferr) return -1;
        }
    }
    uint8_t **PP = malloc(np * sizeof(uint8_t *));
    m = meta + e->moff + e->hlen;
    int s = 0, nn = 0;
    for (int k = 0; k < np; k++) {
        uint8_t t = *m++;
        uint16_t q = 0;
        if (t == K_COPY || t == K_NOT) { memcpy(&q, m, 2); m += 2; }
        switch (t) {
        case K_ZERO: PP[k] = Z; break;
        case K_ONES: PP[k] = O; break;
        case K_COPY: PP[k] = PP[q]; break;
        case K_NOT: {
            uint8_t *x = N + (int64_t)nn++ * bb;
            for (int64_t i = 0; i < bb; i++) x[i] = (uint8_t)~PP[q][i];
            PP[k] = x; break;
        }
        default:
            PP[k] = S + (int64_t)s++ * bb;
            if (t == K_STORED_X) trans_inv(PP[k], bb);
        }
    }
    unpack_block(PP, rb, L, sym, out, nth);
    free(PP);
    if (pre) {               /* expand in place, last row first: source index k(i) <= i */
        int64_t k = rb;
        for (int64_t i = rfull - 1; i >= 0; i--) {
            int is_rep = (Rp[i >> 3] >> (7 - (i & 7))) & 1;
            /* k = kept rows in [0, i]; a kept row is compact row k-1, a repeated row
             * copies the last kept row before it, also compact row k-1 */
            int64_t src = k - 1;
            if (!is_rep) k--;
            if (src < 0) return -1;
            if (src != i) memcpy(out + i * (W + 1), out + src * (W + 1), W + 1);
        }
        if (k != 0) return -1;
    }
    return 0;
}

int xt2_decode(const uint8_t *src, const uint8_t *meta, int64_t meta_len, int64_t rows, int W,
               const int32_t *nb, const uint8_t *sym, uint8_t *out, int nth)
{
    layout_t *L = malloc(sizeof(layout_t));
    make_layout(L, W, nb);
    int64_t R;
    memcpy(&R, meta, 8);
    int64_t nblk = (rows + R - 1) / R;
    dblk_t *E = malloc(nblk * sizeof(dblk_t));
    int64_t mp = 8, fo = 0;
    for (int64_t b = 0; b < nblk; b++) {         /* D1: serial index parse */
        if (mp + 22 > meta_len) { free(E); free(L); return -1; }
        memcpy(&E[b].csize, meta + mp, 8);
        memcpy(&E[b].nst, meta + mp + 8, 4);
        memcpy(&E[b].nk, meta + mp + 12, 4);
        memcpy(&E[b].per, meta + mp + 16, 4);
        memcpy(&E[b].nfr, meta + mp + 20, 2);
        E[b].hlen = 22 + 8 * (int64_t)E[b].nfr;
        E[b].moff = mp; E[b].foff = fo;
        fo += E[b].csize;
        mp += E[b].hlen;
        for (int k = 0; k < L->nplanes; k++) { uint8_t t = meta[mp++]; if (t == K_COPY || t == K_NOT) mp += 2; }
    }
    int err = 0;
    int outer = nblk < nth ? (int)nblk : nth, inner = nth / outer;
    if (inner < 1) inner = 1;
    omp_set_max_active_levels(2);
    #pragma omp parallel num_threads(outer) reduction(|:err)
    {
        ZSTD_DCtx *d = ZSTD_createDCtx();
        ZSTD_DCtx_setParameter(d, ZSTD_d_windowLogMax, 31);
        uint8_t *sc = NULL; int64_t cap = 0;
        #pragma omp for schedule(dynamic, 1)
        for (int64_t b = 0; b < nblk; b++) {
            int64_t rb = rows - b * R < R ? rows - b * R : R;
            if (decode_block(d, src, &E[b], meta, rb, L, sym, out + b * R * (W + 1), &sc, &cap, inner)) err = 1;
        }
        free(sc); ZSTD_freeDCtx(d);
    }
    free(E); free(L);
    return err ? -1 : 0;
}

/* ----------------------------------------------------- plain zstd paths */
int64_t xt2_zstd(const uint8_t *src, int64_t n, uint8_t *dst, int64_t cap, int level, int wlog,
                 int ldm, int workers)
{
    ZSTD_CCtx *c = ZSTD_createCCtx();
    ZSTD_CCtx_setParameter(c, ZSTD_c_compressionLevel, level);
    if (wlog) ZSTD_CCtx_setParameter(c, ZSTD_c_windowLog, wlog);
    if (ldm) ZSTD_CCtx_setParameter(c, ZSTD_c_enableLongDistanceMatching, 1);
    if (workers) ZSTD_CCtx_setParameter(c, ZSTD_c_nbWorkers, workers);
    size_t r = ZSTD_compress2(c, dst, cap, src, n);
    ZSTD_freeCCtx(c);
    return ZSTD_isError(r) ? -1 : (int64_t)r;
}

int64_t xt2_unzstd(const uint8_t *src, int64_t n, uint8_t *dst, int64_t cap)
{
    ZSTD_DCtx *d = ZSTD_createDCtx();
    ZSTD_DCtx_setParameter(d, ZSTD_d_windowLogMax, 31);
    size_t r = ZSTD_decompressDCtx(d, dst, cap, src, n);
    ZSTD_freeDCtx(d);
    return ZSTD_isError(r) ? -1 : (int64_t)r;
}

size_t xt2_bound(size_t n) { return ZSTD_compressBound(n); }

int xt2_equal(const uint8_t *a, const uint8_t *b, int64_t n, int nth)
{
    int diff = 0;
    #pragma omp parallel for num_threads(nth) reduction(|:diff) schedule(static)
    for (int64_t k = 0; k < (n + (1 << 24) - 1) >> 24; k++) {
        int64_t o = k << 24, len = o + (1 << 24) <= n ? (1 << 24) : n - o;
        if (memcmp(a + o, b + o, len)) diff = 1;
    }
    return !diff;
}
