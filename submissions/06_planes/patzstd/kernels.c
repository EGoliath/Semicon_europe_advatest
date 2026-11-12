/* Fast transform kernels for patzstd (OpenMP).
 *
 * Vector chunk layout in memory: rows x (W+1) bytes, last byte of a row '\n'.
 * Bitpack layout: W pin streams, each nb=(rows+7)/8 bytes, MSB = earliest row
 * (identical to numpy.packbits(bits.T, axis=1)).
 *
 * Build: gcc -O3 -march=native -fopenmp -shared -fPIC kernels.c -o libpatk.so
 */
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdlib.h>
#include <omp.h>

typedef uint8_t u8;

void pk_set_threads(int n) { if (n > 0) omp_set_num_threads(n); }

/* OR the symbol-presence map (W x 256 bytes) of this chunk into `pres`.
 * Returns 0 if the chunk is a clean grid, -1 otherwise. */
int pk_analyse(const u8 *buf, size_t rows, int W, u8 *pres)
{
    const size_t stride = (size_t)W + 1;
    int bad = 0;
    #pragma omp parallel
    {
        u8 *loc = calloc((size_t)W * 256, 1);
        #pragma omp for schedule(static) reduction(|:bad)
        for (size_t r = 0; r < rows; r++) {
            const u8 *row = buf + r * stride;
            if (row[W] != '\n') bad = 1;
            for (int c = 0; c < W; c++) {
                u8 s = row[c];
                loc[(size_t)c * 256 + s] = 1;
            }
        }
        #pragma omp critical
        for (size_t i = 0; i < (size_t)W * 256; i++) pres[i] |= loc[i];
        free(loc);
    }
    /* a '\n' inside a row means ragged lines */
    for (int c = 0; c < W; c++) if (pres[(size_t)c * 256 + '\n']) bad = 1;
    return bad ? -1 : 0;
}

/* rows x (W+1) -> W x nb bits (1 = symbol != base[c]) */
void pk_pack(const u8 *buf, size_t rows, int W, const u8 *base, u8 *out)
{
    const size_t stride = (size_t)W + 1, nb = (rows + 7) / 8;
    #pragma omp parallel
    {
        u8 *acc = malloc(W);
        #pragma omp for schedule(static)
        for (size_t b = 0; b < nb; b++) {
            size_t r0 = b * 8, n = rows - r0 < 8 ? rows - r0 : 8;
            memset(acc, 0, W);
            for (size_t k = 0; k < n; k++) {
                const u8 *row = buf + (r0 + k) * stride;
                const u8 bit = (u8)(0x80 >> k);
                for (int c = 0; c < W; c++)            /* vectorises */
                    acc[c] |= (u8)(-(row[c] != base[c])) & bit;
            }
            for (int c = 0; c < W; c++) out[(size_t)c * nb + b] = acc[c];
        }
        free(acc);
    }
}

/* W x nb bits -> rows x (W+1) symbols with '\n' */
void pk_unpack(const u8 *in, size_t rows, int W, const u8 *base, const u8 *alt, u8 *out)
{
    const size_t stride = (size_t)W + 1, nb = (rows + 7) / 8;
    u8 x[W];
    for (int c = 0; c < W; c++) x[c] = base[c] ^ alt[c];
    #pragma omp parallel
    {
        u8 *acc = malloc(W);
        #pragma omp for schedule(static)
        for (size_t b = 0; b < nb; b++) {
            size_t r0 = b * 8, n = rows - r0 < 8 ? rows - r0 : 8;
            for (int c = 0; c < W; c++) acc[c] = in[(size_t)c * nb + b];
            for (size_t k = 0; k < n; k++) {
                u8 *row = out + (r0 + k) * stride;
                const int sh = 7 - (int)k;
                for (int c = 0; c < W; c++)            /* vectorises */
                    row[c] = base[c] ^ (x[c] & (u8)(-((acc[c] >> sh) & 1)));
                row[W] = '\n';
            }
        }
        free(acc);
    }
}

/* rows x (W+1) -> W x rows bytes (newline dropped), blocked for cache */
void pk_transpose(const u8 *buf, size_t rows, int W, u8 *out)
{
    const size_t stride = (size_t)W + 1, B = 64;
    #pragma omp parallel for schedule(static)
    for (size_t r0 = 0; r0 < rows; r0 += B) {
        size_t r1 = r0 + B < rows ? r0 + B : rows;
        for (int c = 0; c < W; c++)
            for (size_t r = r0; r < r1; r++)
                out[(size_t)c * rows + r] = buf[r * stride + c];
    }
}

void pk_untranspose(const u8 *in, size_t rows, int W, u8 *out)
{
    const size_t stride = (size_t)W + 1, B = 64;
    #pragma omp parallel for schedule(static)
    for (size_t r0 = 0; r0 < rows; r0 += B) {
        size_t r1 = r0 + B < rows ? r0 + B : rows;
        for (int c = 0; c < W; c++)
            for (size_t r = r0; r < r1; r++)
                out[r * stride + c] = in[(size_t)c * rows + r];
        for (size_t r = r0; r < r1; r++) out[r * stride + W] = '\n';
    }
}

/* ====================================================================== */
/*  Ternary ("3^5 = 243 <= 256") packing                                  */
/* ====================================================================== */
static const unsigned POW3[6] = {1, 3, 9, 27, 81, 243};
static u8 DEC5[243][5];

void t5_init(void)
{
    for (int v = 0; v < 243; v++) {
        int x = v;
        for (int k = 0; k < 5; k++) { DEC5[v][k] = (u8)(x % 3); x /= 3; }
    }
}

/* ---- generic stream codec (any bytes) --------------------------------
 * token   0..242 : full group of 5 digits, C = d0 + 3d1 + 9d2 + 27d3 + 81d4
 * token   243    : newline '\n'
 * token 244..247 : partial group of k = token-243 (1..4) digits, next byte = value (< 3^k)
 * token   248    : literal, next byte is the original byte
 * token 249..255 : invalid
 * lut[b] = digit 0..2 for alphabet bytes, 255 otherwise ('\n' must be 255). */
size_t t5s_encode(const u8 *in, size_t n, const u8 *lut, u8 *out)
{
    u8 *o = out;
    unsigned acc = 0, k = 0;
    for (size_t i = 0; i < n; i++) {
        const u8 b = in[i], d = lut[b];
        if (d < 3) {
            acc += d * POW3[k];
            if (++k == 5) { *o++ = (u8)acc; acc = 0; k = 0; }
            continue;
        }
        if (k) { *o++ = (u8)(243 + k); *o++ = (u8)acc; acc = 0; k = 0; }
        if (b == '\n') *o++ = 243;
        else { *o++ = 248; *o++ = b; }
    }
    if (k) { *o++ = (u8)(243 + k); *o++ = (u8)acc; }
    return (size_t)(o - out);
}

/* returns decoded length, or <0: -1 bad token, -2 output overflow,
 * -3 truncated token, -4 partial value out of range, -5 non-canonical literal */
long long t5s_decode(const u8 *in, size_t m, const u8 *alph, u8 *out, size_t cap, int use_lut)
{
    size_t i = 0, j = 0;
    while (i < m) {
        const u8 c = in[i++];
        if (c < 243) {
            if (j + 5 > cap) return -2;
            if (use_lut) {
                const u8 *d = DEC5[c];
                out[j] = alph[d[0]]; out[j + 1] = alph[d[1]]; out[j + 2] = alph[d[2]];
                out[j + 3] = alph[d[3]]; out[j + 4] = alph[d[4]];
            } else {
                unsigned x = c;
                for (int k = 0; k < 5; k++) { out[j + k] = alph[x % 3]; x /= 3; }
            }
            j += 5;
        } else if (c == 243) {
            if (j >= cap) return -2;
            out[j++] = '\n';
        } else if (c <= 247) {
            const unsigned k = c - 243u;
            if (i >= m) return -3;
            unsigned v = in[i++];
            if (v >= POW3[k]) return -4;
            if (j + k > cap) return -2;
            for (unsigned t = 0; t < k; t++) { out[j++] = alph[v % 3]; v /= 3; }
        } else if (c == 248) {
            if (i >= m) return -3;
            const u8 b = in[i++];
            if (b == '\n' || b == alph[0] || b == alph[1] || b == alph[2]) return -5;
            if (j >= cap) return -2;
            out[j++] = b;
        } else {
            return -1;
        }
    }
    return (long long)j;
}

/* ---- row-major grid: one file alphabet, G = ceil(W/5) bytes per vector --- */
int t5r_pack(const u8 *buf, size_t rows, int W, const u8 *lut, u8 *out)
{
    const size_t stride = (size_t)W + 1, G = ((size_t)W + 4) / 5;
    int bad = 0;
    #pragma omp parallel for schedule(static) reduction(|:bad)
    for (size_t r = 0; r < rows; r++) {
        const u8 *row = buf + r * stride;
        u8 *o = out + r * G;
        for (size_t g = 0; g < G; g++) {
            unsigned acc = 0;
            const size_t c0 = g * 5, n = (size_t)W - c0 < 5 ? (size_t)W - c0 : 5;
            for (size_t k = 0; k < n; k++) {
                const u8 d = lut[row[c0 + k]];
                bad |= d > 2;
                acc += d * POW3[k];
            }
            o[g] = (u8)acc;
        }
    }
    return bad ? -1 : 0;
}

int t5r_unpack(const u8 *in, size_t rows, int W, const u8 *alph, u8 *out, int use_lut)
{
    const size_t stride = (size_t)W + 1, G = ((size_t)W + 4) / 5;
    int bad = 0;
    #pragma omp parallel for schedule(static) reduction(|:bad)
    for (size_t r = 0; r < rows; r++) {
        const u8 *g8 = in + r * G;
        u8 *row = out + r * stride;
        for (size_t g = 0; g < G; g++) {
            unsigned v = g8[g];
            const size_t c0 = g * 5, n = (size_t)W - c0 < 5 ? (size_t)W - c0 : 5;
            if (v >= POW3[n]) { bad = 1; v = 0; }
            if (use_lut) for (size_t k = 0; k < n; k++) row[c0 + k] = alph[DEC5[v][k]];
            else for (size_t k = 0; k < n; k++) { row[c0 + k] = alph[v % 3]; v /= 3; }
        }
        row[W] = '\n';
    }
    return bad ? -1 : 0;
}

/* ---- pin-major, per-pin radix: cls 0 = constant (0 bits), 1 = binary
 * (8 vectors/byte, MSB first), 2 = ternary (5 vectors/byte).
 * Output: pins in order, pin c occupies size(cls[c], rows) bytes.
 * Work is split in blocks of 40 vectors (= 5 binary bytes = 8 ternary bytes). */
static size_t mx_size(u8 cls, size_t rows)
{
    return cls == 1 ? (rows + 7) / 8 : cls == 2 ? (rows + 4) / 5 : 0;
}

size_t mx_payload(size_t rows, int W, const u8 *cls)
{
    size_t s = 0;
    for (int c = 0; c < W; c++) s += mx_size(cls[c], rows);
    return s;
}

int mx_pack(const u8 *buf, size_t rows, int W, const u8 *cls, const u8 *lut, u8 *out)
{
    const size_t stride = (size_t)W + 1, nblk = (rows + 39) / 40;
    size_t *offs = malloc(sizeof(size_t) * (size_t)(W ? W : 1));
    size_t s = 0;
    for (int c = 0; c < W; c++) { offs[c] = s; s += mx_size(cls[c], rows); }
    int bad = 0;
    #pragma omp parallel for schedule(static) reduction(|:bad)
    for (size_t b = 0; b < nblk; b++) {
        const size_t r0 = b * 40, n = rows - r0 < 40 ? rows - r0 : 40;
        const u8 *blk = buf + r0 * stride;
        for (int c = 0; c < W; c++) {
            const u8 *L = lut + (size_t)c * 256;
            if (cls[c] == 1) {
                u8 *o = out + offs[c] + b * 5;
                for (size_t j = 0; j * 8 < n; j++) {
                    unsigned acc = 0;
                    for (size_t t = 0; t < 8 && j * 8 + t < n; t++) {
                        const u8 d = L[blk[(j * 8 + t) * stride + c]];
                        bad |= d > 1;
                        acc |= (unsigned)(d & 1) << (7 - t);
                    }
                    o[j] = (u8)acc;
                }
            } else if (cls[c] == 2) {
                u8 *o = out + offs[c] + b * 8;
                for (size_t j = 0; j * 5 < n; j++) {
                    unsigned acc = 0;
                    for (size_t t = 0; t < 5 && j * 5 + t < n; t++) {
                        const u8 d = L[blk[(j * 5 + t) * stride + c]];
                        bad |= d > 2;
                        acc += d * POW3[t];
                    }
                    o[j] = (u8)acc;
                }
            } else {
                for (size_t t = 0; t < n; t++) bad |= L[blk[t * stride + c]] != 0;
            }
        }
    }
    free(offs);
    return bad ? -1 : 0;
}

int mx_unpack(const u8 *in, size_t rows, int W, const u8 *cls, const u8 *alph, u8 *out, int use_lut)
{
    const size_t stride = (size_t)W + 1, nblk = (rows + 39) / 40;
    size_t *offs = malloc(sizeof(size_t) * (size_t)(W ? W : 1));
    size_t s = 0;
    for (int c = 0; c < W; c++) { offs[c] = s; s += mx_size(cls[c], rows); }
    int bad = 0;
    #pragma omp parallel for schedule(static) reduction(|:bad)
    for (size_t b = 0; b < nblk; b++) {
        const size_t r0 = b * 40, n = rows - r0 < 40 ? rows - r0 : 40;
        u8 *blk = out + r0 * stride;
        for (int c = 0; c < W; c++) {
            const u8 *A = alph + (size_t)c * 3;
            if (cls[c] == 1) {
                const u8 *p = in + offs[c] + b * 5;
                for (size_t j = 0; j * 8 < n; j++) {
                    const unsigned v = p[j];
                    for (size_t t = 0; t < 8 && j * 8 + t < n; t++)
                        blk[(j * 8 + t) * stride + c] = A[(v >> (7 - t)) & 1];
                }
            } else if (cls[c] == 2) {
                const u8 *p = in + offs[c] + b * 8;
                for (size_t j = 0; j * 5 < n; j++) {
                    unsigned v = p[j];
                    const size_t m = n - j * 5 < 5 ? n - j * 5 : 5;
                    if (v >= POW3[m]) { bad = 1; v = 0; }
                    if (use_lut) for (size_t t = 0; t < m; t++) blk[(j * 5 + t) * stride + c] = A[DEC5[v][t]];
                    else for (size_t t = 0; t < m; t++) { blk[(j * 5 + t) * stride + c] = A[v % 3]; v /= 3; }
                }
            } else {
                for (size_t t = 0; t < n; t++) blk[t * stride + c] = A[0];
            }
        }
        for (size_t t = 0; t < n; t++) blk[t * stride + W] = '\n';
    }
    free(offs);
    return bad ? -1 : 0;
}

/* byte histogram (4 interleaved tables to avoid store-to-load stalls) */
void t5_hist(const u8 *in, size_t n, uint64_t *out)
{
    uint32_t h[4][256];
    memset(h, 0, sizeof h);
    memset(out, 0, 256 * sizeof(uint64_t));
    size_t i = 0;
    while (i < n) {
        size_t end = n - i > ((size_t)1 << 30) ? i + ((size_t)1 << 30) : n;   /* avoid u32 overflow */
        for (; i + 4 <= end; i += 4) {
            h[0][in[i]]++; h[1][in[i + 1]]++; h[2][in[i + 2]]++; h[3][in[i + 3]]++;
        }
        for (; i < end; i++) h[0][in[i]]++;
        for (int b = 0; b < 256; b++) {
            out[b] += (uint64_t)h[0][b] + h[1][b] + h[2][b] + h[3][b];
            h[0][b] = h[1][b] = h[2][b] = h[3][b] = 0;
        }
    }
}
