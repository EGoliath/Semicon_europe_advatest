/*
 * pcm: context-mixing binary arithmetic coder for pin bit streams (new in patamd).
 *
 * A frame is n pins x nb bytes (each pin's bits MSB-first, earliest vector first,
 * exactly as planes stores them). Every bit is predicted by a logistic mix of:
 *
 *   - 6 history models of the SAME pin (last 4/8/12/16/24/32/48/64 bits),
 *   - a match model (longest earlier repeat of the last 32 bits, anywhere in the
 *     frame: the LZ redundancy zstd/xz find, but predicted bit by bit),
 *   - a lag model: bits around t-L of the same pin (L = per-pin period, 0 = off),
 *   - a reference model: bits around t of an earlier pin of the frame (-1 = off),
 *
 * then refined by two APM/SSE stages and coded with a 32-bit binary arithmetic
 * coder (carry-less, lpaq style, 16-bit probabilities). Encoder and decoder run
 * the identical model, so the format is defined by this file + level.
 *
 * Tables are shared by all pins of a frame (what one pin teaches helps the next);
 * frames are independent, so frames run in parallel (one model per thread).
 */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define NIN 14                      /* mixer inputs (incl. bias) */

#define NMS 3
#define MMSZ (4 * 64 * 2 + 1)

/* tunables (fixed per level in the format; settable for experiments) */
/* defaults = the format (tuned on real pin streams, see results/IDEAS.md section 11);
   T_NH / T_MB = 0 -> table sizes follow the level and the stream length */
static int T_VERIFY = 1, T_NH = 0, T_MB = 0, T_PHASE = 8, T_LR = 8, T_LRSH = 14, T_LIM = 127,
           T_MCTX = 40, T_MCTX2 = 64, T_APMR = 5;
void pcm_tune(int k, int v) {
    if (k == 0) T_LR = v; else if (k == 1) T_LRSH = v; else if (k == 2) T_LIM = v;
    else if (k == 3) T_MCTX = v; else if (k == 4) T_MCTX2 = v; else if (k == 5) T_APMR = v; else if (k == 6) T_PHASE = v; else if (k == 7) T_NH = v; else if (k == 8) T_MB = v; else if (k == 9) T_VERIFY = v;
}

static int16_t stretch_t[4096];
static int squash_i(int d) {        /* d: stretch domain (-2047..2047) -> 12-bit p */
    if (d > 2047) d = 2047;
    if (d < -2047) d = -2047;
    static const int t[33] = {1, 2, 3, 6, 10, 16, 27, 45, 73, 120, 194, 310, 488, 747, 1101, 1546,
        2047, 2549, 2994, 3348, 3607, 3785, 3901, 3975, 4024, 4050, 4068, 4079, 4085, 4089, 4092, 4093, 4094};
    int w = d & 127;
    d = (d >> 7) + 16;
    return (t[d] * (128 - w) + t[d + 1] * w + 64) >> 7;
}
static void init_tables(void) {
    static int done = 0;
    if (done) return;
    int pi = 0;
    for (int x = -2047; x <= 2047; x++) {
        int v = squash_i(x);
        for (int j = pi; j <= v; j++) stretch_t[j] = (int16_t)x;
        pi = v + 1;
    }
    for (int j = pi; j < 4096; j++) stretch_t[j] = 2047;
    done = 1;
}
static inline int st(int p16) { return stretch_t[p16 >> 4]; }

/* adaptive probability with count-based rate: hi 22 bits p, lo 10 bits n */
static int rec_t[1024];
/* entries are stored XOR 0x80000000 so that calloc'ed (zero) memory means p = 0.5, n = 0 */
static inline int sm_p(uint32_t e) { return (e ^ 0x80000000u) >> 16; }  /* 16-bit p */
static inline void sm_upd(uint32_t *e, int bit, int lim) {
    uint32_t v = *e ^ 0x80000000u;
    int n = v & 1023, p = v >> 10;                                    /* 22-bit p */
    int target = bit ? (1 << 22) - 1 : 0;
    p += (int)(((int64_t)(target - p) * rec_t[n]) >> 16);
    if (n < lim) n++;
    *e = (((uint32_t)p << 10) | n) ^ 0x80000000u;
}

typedef struct {
    int nh;                         /* hashed table bits */
    uint32_t *h4, *h8, *hb[6];      /* direct 4/8 (+phase) + bucketed 12/16/24/32/48/64 */
    uint32_t *lagm, *refm, *mm;
    uint32_t *mt, *mt2;             /* match tables: hash(last MCTX / MCTX2 bits) -> global bit pos + 1 */
    uint32_t *mm2;
    int mbits;
    int32_t w[64][NIN];             /* mixer weights, 64 sets */
    uint16_t apm1[1024 * 33], apm2[65536 * 33];
    int lim;
} Model;

static void apm_init(uint16_t *a, int n) {
    for (int i = 0; i < n; i++)
        for (int j = 0; j < 33; j++)
            a[i * 33 + j] = (uint16_t)(squash_i((j - 16) * 128) * 16);
}

static int ilog2(uint64_t x) { int l = 0; while (x >>= 1) l++; return l; }

static Model *model_new(int level, uint64_t nbits) {
    init_tables();
    for (int n = 0; n < 1024; n++) rec_t[n] = (int)(65536.0 / (n + 1.6));
    Model *m = calloc(1, sizeof(Model));
    /* level 1/2/3: hashed tables 2^18/2^20/2^22 entries (1/4/16 MiB each), capped
       for short streams; match tables 2^20 (2^22 at level 3), also capped */
    int cap = ilog2(nbits / 4 + 1) + 2;
    int nh = level <= 1 ? 18 : level == 2 ? 20 : 22, mb = level >= 3 ? 22 : 20;
    if (nh > cap) nh = cap;
    if (mb > cap) mb = cap;
    if (nh < 12) nh = 12;
    if (mb < 12) mb = 12;
    m->nh = T_NH ? T_NH : nh;
    m->mbits = T_MB ? T_MB : mb;
    m->lim = T_LIM;
    size_t H = (size_t)1 << m->nh;
#define ALLOC(x, n) do { x = calloc((n), 4); } while (0)
    ALLOC(m->h4, 16 * 256); ALLOC(m->h8, 256 * 256);
    for (int k = 0; k < 6; k++) m->hb[k] = calloc(H, 4);   /* calloc'ed pages are page aligned */
    ALLOC(m->lagm, 1 << 16); ALLOC(m->refm, 1 << 16); ALLOC(m->mm, NMS * MMSZ); ALLOC(m->mm2, 4);
#undef ALLOC
    m->mt = calloc((size_t)1 << m->mbits, 4);
    m->mt2 = calloc((size_t)1 << m->mbits, 4);
    for (int s = 0; s < 64; s++)
        for (int i = 0; i < NIN; i++) m->w[s][i] = (1 << 16) / 5;
    apm_init(m->apm1, 1024);
    apm_init(m->apm2, 65536);
    return m;
}

static void model_free(Model *m) {
    free(m->h4); free(m->h8);
    for (int k = 0; k < 6; k++) free(m->hb[k]);
    free(m->lagm); free(m->refm); free(m->mm); free(m->mt); free(m->mm2); free(m->mt2);
    free(m);
}

static inline int mbucket(int ml) {
    if (ml < 32) return ml;
    int l = 31 - __builtin_clz((unsigned)ml);
    int b = 32 + (l - 5) * 4 + ((ml >> (l - 2)) & 3);
    return b > 63 ? 63 : b;
}

static inline uint32_t hsh(uint64_t x, int k, int bits) {
    x = (x + (uint64_t)k * 0x9E3779B97F4A7C15ull) * 0xD6E8FEB86659FD93ull;
    x ^= x >> 32;
    x *= 0xD6E8FEB86659FD93ull;
    return (uint32_t)(x >> (64 - bits));
}

static inline int getbit(const uint8_t *buf, uint64_t g) {
    return (buf[g >> 3] >> (7 - (g & 7))) & 1;
}

/* the k (<= 64) bits that end just before bit index g (g >= k), as an integer */
static inline uint64_t bits_before(const uint8_t *buf, uint64_t g, int k) {
    uint64_t v = 0;
    uint64_t s = g - (uint64_t)k;
    uint64_t byte = s >> 3;
    int off = (int)(s & 7);
    /* gather k + off bits starting at byte (at most 9 bytes) */
    int nbytes = (k + off + 7) >> 3;
    unsigned __int128 acc = 0;
    for (int i = 0; i < nbytes; i++) acc = (acc << 8) | buf[byte + i];
    int extra = nbytes * 8 - off - k;
    acc >>= extra;
    v = (uint64_t)acc;
    return k >= 64 ? v : (v & ((1ull << k) - 1));
}

/* bits of `buf` (frame-global bit index) around position g: g-a .. g+b (missing = 0) */
static inline uint32_t window(const uint8_t *buf, int64_t lo, int64_t hi, int64_t g, int a, int b) {
    uint32_t v = 0;
    for (int64_t q = g - a; q <= g + b; q++)
        v = (v << 1) | ((q >= lo && q < hi) ? getbit(buf, (uint64_t)q) : 0);
    return v;
}

/* ---- per-bit prediction state */
typedef struct {
    uint32_t *e[NIN];
    int x[NIN];
    int ws, pr, pmix, a1, a2, wa1, wa2;
    int lb;
} Pred;

/* match model state: ptr = frame bit index of the predicted bit */
typedef struct { uint64_t ptr; int len, miss, on, ex, idx; } MS;

static inline int predict(Model *m, Pred *P, uint64_t h, int64_t t, int64_t g, int64_t pin0,
                          int64_t nbits, const uint8_t *buf, int lag, int64_t ref0, MS *ms, const uint32_t *bk) {
    int k = 0;
    const uint64_t ph = (uint64_t)(t & 7);
    P->e[k++] = &m->h4[(h & 15) | ph << 4];
    P->e[k++] = &m->h8[(h & 255) | ph << 8];
    /* hashed orders: one 64-byte bucket per (order, nibble start); node = partial bits */
    const int node = (1 << (t & 3)) | (int)(h & ((1u << (t & 3)) - 1));
    for (int j = 0; j < 6; j++) P->e[k++] = &m->hb[j][bk[j] + node];
    /* lag: 8 bits at t-L-3..t-L+4 (+ own last 4) */
    uint32_t lc = 0;
    if (lag > 0 && t >= lag)
        lc = window(buf, pin0, pin0 + t, g - lag, 3, 4) | 0x100;
    P->e[k++] = &m->lagm[((lc << 4) | (h & 15)) & 0xFFFF];
    /* reference pin: 7 bits around t (+ own last 4) */
    uint32_t rc = 0;
    if (ref0 >= 0)
        rc = window(buf, ref0, ref0 + nbits, ref0 + t, 3, 3) | 0x80;
    P->e[k++] = &m->refm[((rc << 4) | (h & 15)) & 0xFFFF];
    /* match models: 0 sticky (keeps its distance through mismatches), 1/2 greedy */
    for (int j = 0; j < NMS; j++) {
        MS *q = &ms[j];
        int idx = MMSZ - 1;
        if (q->on && q->ptr < (uint64_t)g) {
            q->ex = getbit(buf, q->ptr);
            idx = ((q->miss > 3 ? 3 : q->miss) * 64 + mbucket(q->len)) * 2 + q->ex;
        } else q->on = 0;
        q->idx = idx;
        P->e[k++] = &m->mm[j * MMSZ + idx];
    }
    int ml = ms[1].on ? ms[1].len : 0;
    int lb = !ms[1].on ? 0 : ml < 16 ? 1 : ml < 32 ? 2 : ml < 64 ? 3 : ml < 128 ? 4 : ml < 256 ? 5 : ml < 512 ? 6 : 7;
    P->lb = lb;
    for (int i = 0; i < k; i++) P->x[i] = st(sm_p(*P->e[i]));
    P->x[k] = 256;                                   /* bias */
    /* mixer */
    P->ws = lb * 8 + (int)ph % 8;
    int64_t dot = 0;
    for (int i = 0; i < NIN; i++) dot += (int64_t)P->x[i] * m->w[P->ws][i];
    int d = (int)(dot >> 16);
    P->pmix = squash_i(d);
    /* two APMs: order-8 history and match state x order-4 */
    int s = d < -2047 ? -2047 : d > 2047 ? 2047 : d;
    int pos = (s + 2048) * 32, lo = pos >> 12, wt = pos & 4095;
    P->a1 = (int)(h & 255) * 4 + (lb > 3 ? 3 : lb);          /* 1024 contexts */
    P->a2 = (int)(hsh(h & 0xFFFF, 9, 16));
    P->wa1 = wt;
    uint16_t *A1 = &m->apm1[P->a1 * 33 + lo], *A2 = &m->apm2[P->a2 * 33 + lo];
    int p1 = (A1[0] * (4096 - wt) + A1[1] * wt) >> 12;
    int p2 = (A2[0] * (4096 - wt) + A2[1] * wt) >> 12;
    P->wa2 = lo;
    int pf = (P->pmix * 16 * 2 + p1 + p2) >> 2;            /* 16-bit */
    if (pf < 32) pf = 32;
    if (pf > 65535 - 32) pf = 65535 - 32;
    P->pr = pf;
    return pf;
}

static inline void update(Model *m, Pred *P, int bit, MS *ms) {
    for (int i = 0; i < NIN - 1; i++) sm_upd(P->e[i], bit, m->lim);
    for (int j = 0; j < NMS; j++) {
        MS *q = &ms[j];
        if (!q->on) continue;
        if (q->ex == bit) { q->len++; if (q->len > 32) q->miss = 0; }
        else { q->len = 0; q->miss++; }
    }
    /* mixer */
    int err = ((bit << 12) - P->pmix) * T_LR;
    int32_t *w = m->w[P->ws];
    for (int i = 0; i < NIN; i++) w[i] += (P->x[i] * err) >> T_LRSH;
    /* APMs */
    int lo = P->wa2, wt = P->wa1, tgt = bit ? 65535 : 0;
    uint16_t *A1 = &m->apm1[P->a1 * 33 + lo], *A2 = &m->apm2[P->a2 * 33 + lo];
    if (wt < 2048) { A1[0] += (tgt - A1[0]) >> T_APMR; A2[0] += (tgt - A2[0]) >> T_APMR; }
    else { A1[1] += (tgt - A1[1]) >> T_APMR; A2[1] += (tgt - A2[1]) >> T_APMR; }
}

/* ---- arithmetic coder */
typedef struct { uint32_t x1, x2, x; uint8_t *p, *end; const uint8_t *ip, *iend; int ovf; } AC;

static inline void enc_bit(AC *c, int bit, int p16) {
    uint32_t xm = c->x1 + (uint32_t)(((uint64_t)(c->x2 - c->x1) * (uint32_t)p16) >> 16);
    if (bit) c->x2 = xm; else c->x1 = xm + 1;
    while (((c->x1 ^ c->x2) & 0xFF000000u) == 0) {
        if (c->p < c->end) *c->p++ = (uint8_t)(c->x2 >> 24); else c->ovf = 1;
        c->x1 <<= 8;
        c->x2 = (c->x2 << 8) | 255;
    }
}
static inline int dec_bit(AC *c, int p16) {
    uint32_t xm = c->x1 + (uint32_t)(((uint64_t)(c->x2 - c->x1) * (uint32_t)p16) >> 16);
    int bit = c->x <= xm;
    if (bit) c->x2 = xm; else c->x1 = xm + 1;
    while (((c->x1 ^ c->x2) & 0xFF000000u) == 0) {
        c->x1 <<= 8;
        c->x2 = (c->x2 << 8) | 255;
        c->x = (c->x << 8) | (c->ip < c->iend ? *c->ip++ : 0);
    }
    return bit;
}

/* predict bit = 1 (p16 = P(bit==1)) */
static int64_t run(int enc, const uint8_t *in, size_t inlen, uint8_t *buf, size_t nb, int n,
                   const int32_t *lag, const int32_t *ref, uint8_t *out, size_t cap, int level) {
    Model *m = model_new(level, (uint64_t)nb * 8 * (uint64_t)n);
    AC c = {0, 0xFFFFFFFFu, 0, out, out + cap, in, in + inlen, 0};
    if (!enc) {
        for (int i = 0; i < 4; i++) c.x = (c.x << 8) | (c.ip < c.iend ? *c.ip++ : 0);
        memset(buf, 0, nb * (size_t)n);
    }
    const int64_t nbits = (int64_t)nb * 8;
    const uint32_t mmask = (1u << m->mbits) - 1;
    for (int p = 0; p < n; p++) {
        int64_t pin0 = (int64_t)p * nbits;
        int64_t r0 = (ref[p] >= 0 && ref[p] < p) ? (int64_t)ref[p] * nbits : -1;
        int L = lag[p] > 0 && lag[p] < nbits ? lag[p] : 0;
        uint64_t h = 0;
        Pred P;
        MS ms[NMS];
        memset(ms, 0, sizeof ms);
        const int ctx[NMS] = {T_MCTX, T_MCTX, T_MCTX2};
        static const int ord[6] = {12, 16, 24, 32, 48, 64};
        uint32_t bk[6] = {0};
        const uint32_t hmask = (uint32_t)(((size_t)1 << m->nh) - 16);
        for (int64_t t = 0; t < nbits; t++) {
            int64_t g = pin0 + t;
            if ((t & 3) == 0) {
                uint64_t ph = (uint64_t)(t & 7);
                for (int j = 0; j < 6; j++) {
                    uint64_t hm = ord[j] >= 64 ? h : (h & ((1ull << ord[j]) - 1));
                    bk[j] = (hsh(hm ^ (ph << 58), 11 + j, 32) & hmask);
                    __builtin_prefetch(&m->hb[j][bk[j]]);
                }
            }
            int pr = predict(m, &P, h, t, g, pin0, nbits, buf, L, r0, ms, bk);
            int bit;
            if (enc) {
                bit = getbit(buf, (uint64_t)g);
                enc_bit(&c, bit, pr);
            } else {
                bit = dec_bit(&c, pr);
                if (bit) buf[g >> 3] |= (uint8_t)(0x80 >> (g & 7));
            }
            update(m, &P, bit, ms);
            h = (h << 1) | (uint64_t)bit;
            uint64_t nph = (uint64_t)((t + 1) & 7);
            for (int j = 0; j < NMS; j++) {
                MS *q = &ms[j];
                if (q->on) q->ptr++;
                if (t + 1 < ctx[j] || ((t + 1) & 3)) continue;
                uint64_t cmask = ctx[j] >= 64 ? ~0ull : ((1ull << ctx[j]) - 1);
                uint32_t *tab = j == 2 ? m->mt2 : m->mt;
                uint32_t mh = hsh((h & cmask) ^ (nph << 58), 7 + (j == 2), m->mbits) & mmask;
                int want = j == 0 ? (!q->on || q->miss > 8) : (!q->on || q->len == 0);
                uint32_t cand = tab[mh];
                if (want && cand && T_VERIFY && (cand < (uint32_t)ctx[j] || cand < pin0 ||
                        bits_before(buf, cand, ctx[j]) != (h & cmask)))
                    cand = 0;
                if (want && cand && (!q->on || cand != q->ptr)) {
                    q->ptr = cand;
                    q->on = 1;
                    q->len = 0;
                    q->miss = 0;
                }
                if (j != 0) tab[mh] = (uint32_t)(g + 1);
            }
        }
    }
    int64_t r = 0;
    if (enc) {
        for (int i = 0; i < 4; i++) {
            if (c.p < c.end) *c.p++ = (uint8_t)(c.x1 >> 24); else c.ovf = 1;
            c.x1 <<= 8;
        }
        r = c.ovf ? -1 : (int64_t)(c.p - out);
    }
    model_free(m);
    return r;
}

/* returns compressed length, or -1 if it does not fit in cap */
int64_t pcm_encode(const uint8_t *in, size_t nb, int n, const int32_t *lag, const int32_t *ref,
                   uint8_t *out, size_t cap, int level) {
    return run(1, NULL, 0, (uint8_t *)in, nb, n, lag, ref, out, cap, level);
}

int64_t pcm_decode(const uint8_t *in, size_t inlen, size_t nb, int n, const int32_t *lag,
                   const int32_t *ref, uint8_t *out, int level) {
    return run(0, in, inlen, out, nb, n, lag, ref, NULL, 0, level);
}
