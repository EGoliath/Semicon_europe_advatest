/*
 * extra_tests kernels -- standalone, does NOT share code with patzstd/ or patamd/.
 *
 * Principles tested (from the research note):
 *   - transpose rows -> per-pin streams (byte transpose, cache-blocked tiles)
 *   - bit packing: 1 bit/vector for 2-symbol pins, 2 bits for 3-4 symbol pins
 *   - XOR / delta between rows (row-major bit rows, row[n] ^ row[n-1])
 *   - XOR along time inside a pin plane (bit transitions)
 *   - zstd long-distance matching with a window up to 2 GiB (--long=31)
 *   - RAP-style independent blocks, OpenMP multi-core (de)compression
 *     straight into a preallocated output buffer
 *
 * Build: gcc -O3 -march=native -fopenmp -shared -fPIC pp_kernels.c -lzstd -o libpp.so
 */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <omp.h>
#include <zstd.h>

#define MAXW 4096

/* ---------------------------------------------------------------- scan */
/* Check the grid (every row = W symbols + '\n') and record which byte values
 * occur on each pin. Returns rows, or -1 if the file is not a clean grid. */
int64_t xt_scan(const uint8_t *buf, int64_t n, int W, uint8_t *present, int nth)
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

/* --------------------------------------------- pin-major bit planes */
/* lut[p*256+c] = 2-bit code of symbol c on pin p (code 0 = first-row symbol).
 * off0[p] / off1[p] = offset of the pin's low / high plane in out (-1 = none).
 * Each plane is ceil(rows/8) bytes, MSB = earliest vector.
 * Rows are read sequentially in groups of 8 (one cache-friendly row block),
 * the accumulators for all pins stay in L1. */
void xt_pack_planes(const uint8_t *buf, int64_t rows, int W, const uint8_t *lut,
                    const int64_t *off0, const int64_t *off1, uint8_t *out, int nth)
{
    int64_t nbytes = (rows + 7) / 8;
    #pragma omp parallel num_threads(nth)
    {
        uint8_t a0[MAXW], a1[MAXW];
        #pragma omp for schedule(static, 4096)
        for (int64_t g = 0; g < nbytes; g++) {
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
                if (off0[p] >= 0) out[off0[p] + g] = a0[p];
                if (off1[p] >= 0) out[off1[p] + g] = a1[p];
            }
        }
    }
}

/* sym[p*4+c] = byte for code c on pin p. Writes W symbols + '\n' per row. */
void xt_unpack_planes(const uint8_t *in, int64_t rows, int W, const uint8_t *sym,
                      const int64_t *off0, const int64_t *off1, uint8_t *out, int nth)
{
    int64_t nbytes = (rows + 7) / 8;
    uint8_t S0[MAXW], S1[MAXW], S2[MAXW], S3[MAXW];
    for (int p = 0; p < W; p++) {
        S0[p] = sym[p * 4]; S1[p] = sym[p * 4 + 1]; S2[p] = sym[p * 4 + 2]; S3[p] = sym[p * 4 + 3];
    }
    #pragma omp parallel num_threads(nth)
    {
        uint8_t a0[MAXW], a1[MAXW];
        #pragma omp for schedule(static, 4096)
        for (int64_t g = 0; g < nbytes; g++) {
            for (int p = 0; p < W; p++) {
                a0[p] = off0[p] >= 0 ? in[off0[p] + g] : 0;
                a1[p] = off1[p] >= 0 ? in[off1[p] + g] : 0;
            }
            for (int r = 0; r < 8; r++) {
                int64_t row = g * 8 + r;
                if (row >= rows) break;
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

/* ------------------------------------- bit transitions along time */
/* per plane: d_t = x_t ^ x_{t-1} (bit level, x_{-1} = 0). Clock pins become
 * all-ones, slow pins become almost all-zeros. In place. */
void xt_trans_fwd(uint8_t *buf, int64_t nplanes, int64_t nbytes, int nth)
{
    #pragma omp parallel for num_threads(nth) schedule(dynamic, 1)
    for (int64_t k = 0; k < nplanes; k++) {
        uint8_t *x = buf + k * nbytes, prev = 0;
        for (int64_t i = 0; i < nbytes; i++) {
            uint8_t v = x[i];
            x[i] = (uint8_t)(v ^ ((v >> 1) | (uint8_t)(prev << 7)));
            prev = v & 1;
        }
    }
}

void xt_trans_inv(uint8_t *buf, int64_t nplanes, int64_t nbytes, int nth)
{
    #pragma omp parallel for num_threads(nth) schedule(dynamic, 1)
    for (int64_t k = 0; k < nplanes; k++) {
        uint8_t *x = buf + k * nbytes, carry = 0;
        for (int64_t i = 0; i < nbytes; i++) {
            uint8_t v = x[i];
            v ^= v >> 1; v ^= v >> 2; v ^= v >> 4;   /* prefix XOR from the MSB */
            if (carry) v ^= 0xFF;
            x[i] = v;
            carry = v & 1;
        }
    }
}

/* -------------------------------------------- byte transpose (8 bit) */
#define TILE 256
/* out[p*rows + r] = buf[r*(W+1) + p]; newlines are dropped. */
void xt_transpose(const uint8_t *buf, int64_t rows, int W, uint8_t *out, int nth)
{
    int64_t nt = (rows + TILE - 1) / TILE;
    #pragma omp parallel for num_threads(nth) schedule(static)
    for (int64_t t = 0; t < nt; t++) {
        int64_t r0 = t * TILE, r1 = r0 + TILE < rows ? r0 + TILE : rows;
        for (int p = 0; p < W; p++) {
            uint8_t *d = out + (int64_t)p * rows;
            for (int64_t r = r0; r < r1; r++) d[r] = buf[r * (W + 1) + p];
        }
    }
}

void xt_untranspose(const uint8_t *in, int64_t rows, int W, uint8_t *out, int nth)
{
    int64_t nt = (rows + TILE - 1) / TILE;
    #pragma omp parallel for num_threads(nth) schedule(static)
    for (int64_t t = 0; t < nt; t++) {
        int64_t r0 = t * TILE, r1 = r0 + TILE < rows ? r0 + TILE : rows;
        for (int p = 0; p < W; p++) {
            const uint8_t *s = in + (int64_t)p * rows;
            for (int64_t r = r0; r < r1; r++) out[r * (W + 1) + p] = s[r];
        }
        for (int64_t r = r0; r < r1; r++) out[r * (W + 1) + W] = '\n';
    }
}

/* ------------------------------- row-major bit rows + row XOR delta */
/* Row r -> B bytes: pins in order, nb[p] bits each (code bits, MSB first).
 * out row r = packed(r) ^ packed(r-1). tmp: rows*B scratch. */
static inline void pack_row(const uint8_t *s, int W, const uint8_t *lut, const int32_t *nb,
                            int B, uint8_t *d)
{
    memset(d, 0, B);
    int bit = 0;
    for (int p = 0; p < W; p++) {
        int k = nb[p];
        if (!k) continue;
        uint8_t c = lut[p * 256 + s[p]];
        for (int j = k - 1; j >= 0; j--, bit++)
            if ((c >> j) & 1) d[bit >> 3] |= (uint8_t)(0x80 >> (bit & 7));
    }
}

void xt_pack_rows(const uint8_t *buf, int64_t rows, int W, const uint8_t *lut,
                  const int32_t *nb, int B, int xor_rows, uint8_t *tmp, uint8_t *out, int nth)
{
    uint8_t *dst = xor_rows ? tmp : out;
    #pragma omp parallel for num_threads(nth) schedule(static, 65536)
    for (int64_t r = 0; r < rows; r++) pack_row(buf + r * (W + 1), W, lut, nb, B, dst + r * B);
    if (!xor_rows) return;
    #pragma omp parallel for num_threads(nth) schedule(static, 65536)
    for (int64_t r = 0; r < rows; r++)
        for (int i = 0; i < B; i++)
            out[r * B + i] = (uint8_t)(tmp[r * B + i] ^ (r ? tmp[(r - 1) * B + i] : 0));
}

static inline void unpack_row(const uint8_t *row, int W, const uint8_t *sym, const int32_t *nb,
                              uint8_t *d)
{
    int bit = 0;
    for (int p = 0; p < W; p++) {
        int k = nb[p], c = 0;
        for (int j = 0; j < k; j++, bit++)
            c = (c << 1) | ((row[bit >> 3] >> (7 - (bit & 7))) & 1);
        d[p] = sym[p * 4 + c];
    }
    d[W] = '\n';
}

/* Parallel prefix-XOR (two passes over blocks), fused with the unpack. */
void xt_unpack_rows(const uint8_t *in, int64_t rows, int W, const uint8_t *sym,
                    const int32_t *nb, int B, int xor_rows, uint8_t *out, int nth)
{
    if (!xor_rows) {
        #pragma omp parallel for num_threads(nth) schedule(static, 65536)
        for (int64_t r = 0; r < rows; r++) unpack_row(in + r * B, W, sym, nb, out + r * (W + 1));
        return;
    }
    int nblk = nth * 4;
    if (nblk > rows) nblk = rows > 0 ? (int)rows : 1;
    int64_t per = (rows + nblk - 1) / nblk;
    uint8_t *carry = calloc((size_t)(nblk + 1) * B, 1);
    #pragma omp parallel for num_threads(nth) schedule(static)
    for (int b = 0; b < nblk; b++) {
        int64_t r0 = b * per, r1 = r0 + per < rows ? r0 + per : rows;
        uint8_t *c = carry + (int64_t)(b + 1) * B;
        for (int64_t r = r0; r < r1; r++)
            for (int i = 0; i < B; i++) c[i] ^= in[r * B + i];
    }
    for (int b = 1; b <= nblk; b++)
        for (int i = 0; i < B; i++) carry[(int64_t)b * B + i] ^= carry[(int64_t)(b - 1) * B + i];
    #pragma omp parallel for num_threads(nth) schedule(static)
    for (int b = 0; b < nblk; b++) {
        int64_t r0 = b * per, r1 = r0 + per < rows ? r0 + per : rows;
        uint8_t run[MAXW];
        memcpy(run, carry + (int64_t)b * B, B);
        for (int64_t r = r0; r < r1; r++) {
            for (int i = 0; i < B; i++) run[i] ^= in[r * B + i];
            unpack_row(run, W, sym, nb, out + r * (W + 1));
        }
    }
    free(carry);
}

/* ------------------------------------------------------------- zstd */
size_t xt_zstd_bound(size_t n) { return ZSTD_compressBound(n); }

/* One frame. wlog 0 = level default; ldm 1 = long-distance matching;
 * workers 0 = single-threaded. Returns compressed size or -1. */
int64_t xt_zstd_compress(const uint8_t *src, int64_t n, uint8_t *dst, int64_t cap,
                         int level, int wlog, int ldm, int workers)
{
    ZSTD_CCtx *c = ZSTD_createCCtx();
    ZSTD_CCtx_setParameter(c, ZSTD_c_compressionLevel, level);
    if (wlog) ZSTD_CCtx_setParameter(c, ZSTD_c_windowLog, wlog);
    if (ldm) ZSTD_CCtx_setParameter(c, ZSTD_c_enableLongDistanceMatching, 1);
    if (workers) ZSTD_CCtx_setParameter(c, ZSTD_c_nbWorkers, workers);
    ZSTD_CCtx_setPledgedSrcSize(c, (unsigned long long)n);
    size_t r = ZSTD_compress2(c, dst, cap, src, n);
    ZSTD_freeCCtx(c);
    return ZSTD_isError(r) ? -1 : (int64_t)r;
}

int64_t xt_zstd_decompress(const uint8_t *src, int64_t n, uint8_t *dst, int64_t cap)
{
    ZSTD_DCtx *d = ZSTD_createDCtx();
    ZSTD_DCtx_setParameter(d, ZSTD_d_windowLogMax, 31);
    size_t r = ZSTD_decompressDCtx(d, dst, cap, src, n);
    ZSTD_freeDCtx(d);
    return ZSTD_isError(r) ? -1 : (int64_t)r;
}

/* RAP blocks: src cut into bs-byte blocks, each an independent single-threaded
 * frame, compressed by OpenMP threads. dst must hold nblk*bound(bs); frames are
 * compacted in order and csz[] receives each frame's size. Returns total. */
int64_t xt_zstd_rap_compress(const uint8_t *src, int64_t n, int64_t bs, int level, int wlog,
                             uint8_t *dst, int64_t *csz, int nth)
{
    int64_t nblk = (n + bs - 1) / bs;
    size_t bnd = ZSTD_compressBound(bs);
    int err = 0;
    #pragma omp parallel num_threads(nth) reduction(|:err)
    {
        ZSTD_CCtx *c = ZSTD_createCCtx();
        #pragma omp for schedule(dynamic, 1)
        for (int64_t b = 0; b < nblk; b++) {
            int64_t len = b * bs + bs <= n ? bs : n - b * bs;
            ZSTD_CCtx_reset(c, ZSTD_reset_session_and_parameters);
            ZSTD_CCtx_setParameter(c, ZSTD_c_compressionLevel, level);
            if (wlog) ZSTD_CCtx_setParameter(c, ZSTD_c_windowLog, wlog);
            size_t r = ZSTD_compress2(c, dst + b * bnd, bnd, src + b * bs, len);
            if (ZSTD_isError(r)) err = 1; else csz[b] = (int64_t)r;
        }
        ZSTD_freeCCtx(c);
    }
    if (err) return -1;
    int64_t pos = 0;
    for (int64_t b = 0; b < nblk; b++) {
        memmove(dst + pos, dst + b * bnd, csz[b]);
        pos += csz[b];
    }
    return pos;
}

/* Every thread seeks to its frame through the index and decodes it straight
 * into its slot of the preallocated output. */
int64_t xt_zstd_rap_decompress(const uint8_t *src, const int64_t *csz, int64_t nblk,
                               int64_t bs, int64_t n, uint8_t *dst, int nth)
{
    int64_t *off = malloc((nblk + 1) * sizeof(int64_t));
    off[0] = 0;
    for (int64_t b = 0; b < nblk; b++) off[b + 1] = off[b] + csz[b];
    int err = 0;
    #pragma omp parallel num_threads(nth) reduction(|:err)
    {
        ZSTD_DCtx *d = ZSTD_createDCtx();
        #pragma omp for schedule(dynamic, 1)
        for (int64_t b = 0; b < nblk; b++) {
            int64_t len = b * bs + bs <= n ? bs : n - b * bs;
            size_t r = ZSTD_decompressDCtx(d, dst + b * bs, len, src + off[b], csz[b]);
            if (ZSTD_isError(r) || (int64_t)r != len) err = 1;
        }
        ZSTD_freeDCtx(d);
    }
    free(off);
    return err ? -1 : n;
}

/* --------------------------------------------------------- utilities */
int xt_equal(const uint8_t *a, const uint8_t *b, int64_t n)
{
    int diff = 0;
    #pragma omp parallel for reduction(|:diff) schedule(static)
    for (int64_t k = 0; k < (n + (1 << 24) - 1) >> 24; k++) {
        int64_t o = k << 24, len = o + (1 << 24) <= n ? (1 << 24) : n - o;
        if (memcmp(a + o, b + o, len)) diff = 1;
    }
    return !diff;
}
