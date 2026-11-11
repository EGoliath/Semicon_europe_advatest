// tries: structure-aware transforms in front of zstd, benchmarked against plain zstd on the same input.
//   zstd  : plain zstd of the file (the baseline)
//   tp    : per block of R rows, the cells are written column by column (transpose), then zstd
//   pack  : per block and column, the column's own alphabet (k distinct bytes) + ceil(log2 k) bit planes of the
//           symbol index (for 0/1/X: plane0 = is '1', plane1 = is 'X'), then zstd
//   any method + "-long": zstd long-distance matching with a 128 MB window
// File format: zstd = a plain zstd frame (any zstd tool can read it); pack / tp = magic "VPK1" / "VTP1" + one zstd frame.
// build: gcc -O2 tries.c -o tries.exe libzstd.dll
// run:   tries.exe c <method> <level> <in.vec> <out.compr>    compress to a file
//        tries.exe d <in.compr> <out.vec>                     decompress to a file (method taken from the magic)
//        tries.exe --selftest
// Both modes print the wall time and MB/s, where MB = 10^6 bytes of the .vec. Verify with cmp / sha256sum.
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>

// shortcut: hand-declared zstd 1.5 API (WinLibs ships libzstd.dll without zstd.h); use the official header if more API is needed.
typedef struct ZSTD_CCtx_s ZSTD_CCtx;
typedef struct ZSTD_DCtx_s ZSTD_DCtx;
typedef struct { const void *src; size_t size, pos; } ZSTD_inBuffer;
typedef struct { void *dst; size_t size, pos; } ZSTD_outBuffer;
ZSTD_CCtx *ZSTD_createCCtx(void);
size_t ZSTD_freeCCtx(ZSTD_CCtx *);
size_t ZSTD_CCtx_setParameter(ZSTD_CCtx *, int param, int value);
size_t ZSTD_compressStream2(ZSTD_CCtx *, ZSTD_outBuffer *, ZSTD_inBuffer *, int endOp);
size_t ZSTD_CStreamOutSize(void);
ZSTD_DCtx *ZSTD_createDCtx(void);
size_t ZSTD_freeDCtx(ZSTD_DCtx *);
size_t ZSTD_DCtx_setParameter(ZSTD_DCtx *, int param, int value);
size_t ZSTD_decompressStream(ZSTD_DCtx *, ZSTD_outBuffer *, ZSTD_inBuffer *);
unsigned ZSTD_isError(size_t code);
const char *ZSTD_getErrorName(size_t code);
#define ZSTD_c_compressionLevel 100
#define ZSTD_c_windowLog 101
#define ZSTD_c_enableLongDistanceMatching 160
#define ZSTD_c_checksumFlag 201
#define ZSTD_d_windowLogMax 100
#define ZSTD_e_continue 0
#define ZSTD_e_end 2

#define BLOCK (4u << 20)

typedef struct { uint8_t *p; size_t n, cap; } Buf;

static const char *g_out_path; // output being written; removed on failure so no empty/partial file is left behind
static FILE *g_out_f;

static void die(const char *msg, const char *arg) {
    fprintf(stderr, "%s%s\n", msg, arg ? arg : "");
    if (g_out_path) { if (g_out_f) fclose(g_out_f); remove(g_out_path); }
    exit(1);
}

static void reserve(Buf *b, size_t extra) {
    if (b->n + extra <= b->cap) return;
    while (b->n + extra > b->cap) b->cap = b->cap ? b->cap * 2 : 4096;
    if (!(b->p = realloc(b->p, b->cap))) die("out of memory", NULL);
}
static void put(Buf *b, uint8_t c) { reserve(b, 1); b->p[b->n++] = c; }
static void putv(Buf *b, uint64_t v) { for (; v >= 0x80; v >>= 7) put(b, (uint8_t)(v | 0x80)); put(b, (uint8_t)v); }
static int getv(const uint8_t *p, size_t n, size_t *i, uint64_t *v) {
    *v = 0;
    for (int s = 0; s < 64 && *i < n; s += 7) {
        uint8_t c = p[(*i)++];
        *v |= (uint64_t)(c & 0x7F) << s;
        if (!(c & 0x80)) return 1;
    }
    return 0;
}

// ---- zstd stream writer into a Buf
typedef struct { ZSTD_CCtx *c; FILE *f; Buf *mem; uint8_t *out; size_t cap; } ZW;

// raw bytes to the file, or appended to the Buf when f == NULL
static void zw_raw(ZW *w, const void *p, size_t n) {
    if (w->f) { if (fwrite(p, 1, n, w->f) != n) die("write failed", NULL); return; }
    reserve(w->mem, n);
    memcpy(w->mem->p + w->mem->n, p, n);
    w->mem->n += n;
}

static void zw_open(ZW *w, int level, int lng, FILE *f, Buf *mem) {
    w->c = ZSTD_createCCtx();
    w->f = f; w->mem = mem;
    w->cap = ZSTD_CStreamOutSize();
    w->out = malloc(w->cap);
    if (!w->c || !w->out) die("out of memory", NULL);
    ZSTD_CCtx_setParameter(w->c, ZSTD_c_compressionLevel, level);
    ZSTD_CCtx_setParameter(w->c, ZSTD_c_checksumFlag, 1); // XXH64 of the content, checked by the decoder at frame end
    if (lng) { ZSTD_CCtx_setParameter(w->c, ZSTD_c_enableLongDistanceMatching, 1); ZSTD_CCtx_setParameter(w->c, ZSTD_c_windowLog, 27); }
}

static void zw_write(ZW *w, const void *p, size_t n, int end) {
    ZSTD_inBuffer in = {p, n, 0};
    for (;;) {
        ZSTD_outBuffer o = {w->out, w->cap, 0};
        size_t r = ZSTD_compressStream2(w->c, &o, &in, end ? ZSTD_e_end : ZSTD_e_continue);
        if (ZSTD_isError(r)) die("compress failed: ", ZSTD_getErrorName(r));
        zw_raw(w, w->out, o.pos);
        if (end ? r == 0 : in.pos == in.size) return;
    }
}

static void zw_close(ZW *w) { zw_write(w, NULL, 0, 1); ZSTD_freeCCtx(w->c); free(w->out); }

// ---- zstd stream reader over a compressed buffer
typedef struct { ZSTD_DCtx *d; ZSTD_inBuffer in; uint8_t *buf; size_t n, pos, cap; int done; } ZR;

static void zr_open(ZR *r, const uint8_t *p, size_t n, size_t cap) {
    r->d = ZSTD_createDCtx();
    ZSTD_DCtx_setParameter(r->d, ZSTD_d_windowLogMax, 27);
    r->in = (ZSTD_inBuffer){p, n, 0};
    r->cap = cap; r->n = r->pos = 0; r->done = n == 0;
    if (!r->d || !(r->buf = malloc(cap))) die("out of memory", NULL);
}

// Ensures at least `need` (<= cap) unread bytes unless the stream ends first; returns the unread count.
static size_t zr_fill(ZR *r, size_t need) {
    if (r->n - r->pos >= need || r->done) return r->n - r->pos;
    memmove(r->buf, r->buf + r->pos, r->n - r->pos);
    r->n -= r->pos; r->pos = 0;
    while (r->n < r->cap && !r->done) {
        ZSTD_outBuffer o = {r->buf, r->cap, r->n};
        size_t ret = ZSTD_decompressStream(r->d, &o, &r->in);
        if (ZSTD_isError(ret)) die("decompress failed: ", ZSTD_getErrorName(ret));
        r->n = o.pos;
        if (ret == 0 && r->in.pos == r->in.size) r->done = 1;
        else if (r->in.pos == r->in.size && o.pos < o.size) die("decompress failed: truncated frame", NULL); // input gone mid-frame
    }
    return r->n - r->pos;
}

static void zr_close(ZR *r) { ZSTD_freeDCtx(r->d); free(r->buf); }

// ---- output sink: write to a file (f != NULL) and/or compare against the original (ref != NULL)
typedef struct { FILE *f; const uint8_t *ref; uint64_t refn, off, bad; } Sink;

static void sink(Sink *s, const uint8_t *p, size_t n) {
    if (s->f && fwrite(p, 1, n, s->f) != n) die("write failed", NULL);
    if (s->ref) {
        size_t m = s->off >= s->refn ? 0 : (size_t)(s->refn - s->off < n ? s->refn - s->off : n);
        if (m < n) s->bad += n - m;
        if (memcmp(s->ref + s->off, p, m))
            for (size_t i = 0; i < m; i++) s->bad += s->ref[s->off + i] != p[i];
    }
    s->off += n;
}

// ---- grid geometry
typedef struct { uint64_t cols, rows, stride; int eol, final; } Dims;

// Fixed-width lines with one line ending style. NULL on success, else an error.
static const char *scan(const uint8_t *in, uint64_t n, Dims *d) {
    if (!n) return "empty input";
    const uint8_t *nl = memchr(in, '\n', (size_t)n);
    d->cols = nl ? (uint64_t)(nl - in) : n;
    d->eol = 0;
    if (nl) { d->eol = 1; if (d->cols && nl[-1] == '\r') { d->cols--; d->eol = 2; } }
    if (!d->cols) return "first line is empty";
    d->stride = d->cols + d->eol;
    uint64_t rem = n % d->stride;
    if (d->eol && rem != 0 && rem != d->cols) return "file size does not fit fixed-width lines";
    d->rows = d->eol ? n / d->stride + (rem != 0) : 1;
    d->final = d->eol && rem == 0;
    for (uint64_t r = 0; r + 1 < d->rows || (d->final && r < d->rows); r++) {
        const uint8_t *e = in + r * d->stride + d->cols;
        if (d->eol == 1 ? e[0] != '\n' : (e[0] != '\r' || e[1] != '\n')) return "lines are not all the same width / line ending";
    }
    return NULL;
}

static uint64_t g_R; // rows per block (0 = derived from the width)

static uint64_t block_rows(const Dims *d) {
    uint64_t r = g_R ? g_R : (BLOCK / d->cols) & ~7ull;
    if (r > d->rows) r = (d->rows + 7) & ~7ull; // small files: do not allocate a 4 MB block
    return r ? r : 8;
}

static void put_header(ZW *w, const Dims *d) {
    Buf h = {0};
    putv(&h, d->cols); putv(&h, d->rows); put(&h, (uint8_t)d->eol); put(&h, (uint8_t)d->final); putv(&h, block_rows(d));
    zw_write(w, h.p, h.n, 0);
    free(h.p);
}

static const char *get_header(ZR *z, Dims *d, uint64_t *R) {
    size_t n = zr_fill(z, 40), i = z->pos;
    uint64_t eol, final;
    (void)n;
    if (!getv(z->buf, z->n, &i, &d->cols) || !getv(z->buf, z->n, &i, &d->rows) || i + 2 > z->n) return "bad header";
    eol = z->buf[i++]; final = z->buf[i++];
    if (!getv(z->buf, z->n, &i, R) || !d->cols || !*R || eol > 2 || final > 1) return "bad header";
    d->eol = (int)eol; d->final = (int)final; d->stride = d->cols + eol;
    z->pos = i;
    return NULL;
}

// A block of rows in file layout (line endings pre-filled); sinks the bytes the file really has.
static void sink_rows(Sink *s, const uint8_t *out, const Dims *d, uint64_t r0, uint64_t rb) {
    uint64_t len = rb * d->stride;
    if (r0 + rb == d->rows && !d->final) len -= d->eol;
    sink(s, out, (size_t)len);
}

static uint8_t *alloc_rows(const Dims *d, uint64_t R) {
    uint8_t *out = malloc(R * d->stride);
    if (!out) die("out of memory", NULL);
    for (uint64_t r = 0; r < R; r++) {
        if (d->eol == 2) out[r * d->stride + d->cols] = '\r';
        if (d->eol) out[r * d->stride + d->stride - 1] = '\n';
    }
    return out;
}

// ---- tp: transpose
static void tp_enc(const uint8_t *in, const Dims *d, ZW *w) {
    uint64_t R = block_rows(d);
    uint8_t *b = malloc(R * d->cols);
    if (!b) die("out of memory", NULL);
    put_header(w, d);
    for (uint64_t r0 = 0; r0 < d->rows; r0 += R) {
        uint64_t rb = d->rows - r0 < R ? d->rows - r0 : R;
        for (uint64_t r = 0; r < rb; r++) {
            const uint8_t *line = in + (r0 + r) * d->stride;
            for (uint64_t c = 0; c < d->cols; c++) b[c * rb + r] = line[c];
        }
        zw_write(w, b, rb * d->cols, 0);
    }
    free(b);
}

static const char *tp_dec(const uint8_t *cp, size_t cn, Sink *s) {
    Dims d;
    uint64_t R;
    ZR z;
    zr_open(&z, cp, cn, 64);
    const char *err = get_header(&z, &d, &R);
    if (err) return err;
    if (R > (1u << 30) / d.cols) return "bad block size";
    // reopen with a buffer big enough for one block (the header bytes are re-skipped)
    size_t skip = z.pos;
    zr_close(&z);
    zr_open(&z, cp, cn, R * d.cols + 64);
    if (zr_fill(&z, skip) < skip) return "truncated";
    z.pos = skip;
    uint8_t *out = alloc_rows(&d, R);
    for (uint64_t r0 = 0; r0 < d.rows && !err; r0 += R) {
        uint64_t rb = d.rows - r0 < R ? d.rows - r0 : R;
        if (zr_fill(&z, rb * d.cols) < rb * d.cols) { err = "truncated"; break; }
        const uint8_t *b = z.buf + z.pos;
        for (uint64_t c = 0; c < d.cols; c++)
            for (uint64_t r = 0; r < rb; r++) out[r * d.stride + c] = b[c * rb + r];
        z.pos += rb * d.cols;
        sink_rows(s, out, &d, r0, rb);
    }
    if (!err && zr_fill(&z, 1)) err = "trailing data";
    zr_close(&z);
    free(out);
    return err;
}

// ---- pack: per block and column, alphabet + bit planes of the symbol index
static int nbits(int k) { int b = 0; while ((1 << b) < k) b++; return b; }

static void pack_enc(const uint8_t *in, const Dims *d, ZW *w) {
    uint64_t R = block_rows(d), C = d->cols;
    uint8_t *seen = malloc(C * 256), *idx = malloc(C * 256), *bits = malloc(C);
    size_t *plane = malloc(C * sizeof *plane);
    Buf o = {0};
    if (!seen || !idx || !bits || !plane) die("out of memory", NULL);
    put_header(w, d);
    for (uint64_t r0 = 0; r0 < d->rows; r0 += R) {
        uint64_t rb = d->rows - r0 < R ? d->rows - r0 : R, nb = (rb + 7) / 8;
        const uint8_t *base = in + r0 * d->stride;
        memset(seen, 0, C * 256);
        for (uint64_t r = 0; r < rb; r++)
            for (uint64_t c = 0; c < C; c++) seen[c * 256 + base[r * d->stride + c]] = 1;
        // layout per column: [k-1] [alphabet: k bytes] [b planes of nb bytes, bit i of byte g = row 8g+i]
        o.n = 0;
        for (uint64_t c = 0; c < C; c++) {
            size_t at = o.n;
            int k = 0;
            put(&o, 0);
            for (int v = 0; v < 256; v++) if (seen[c * 256 + v]) { idx[c * 256 + v] = (uint8_t)k++; put(&o, (uint8_t)v); }
            o.p[at] = (uint8_t)(k - 1);
            bits[c] = (uint8_t)nbits(k);
            reserve(&o, bits[c] * nb);
            plane[c] = o.n;
            o.n += bits[c] * nb;
        }
        for (uint64_t g = 0; g < nb; g++) { // 8-row tiles keep the source rows in L1
            const uint8_t *t = base + g * 8 * d->stride;
            int cnt = rb - g * 8 < 8 ? (int)(rb - g * 8) : 8;
            for (uint64_t c = 0; c < C; c++) {
                if (!bits[c]) continue;
                unsigned x[8] = {0};
                const uint8_t *ix = idx + c * 256;
                for (int i = 0; i < cnt; i++) {
                    unsigned v = ix[t[i * d->stride + c]];
                    for (int j = 0; j < bits[c]; j++) x[j] |= (v >> j & 1u) << i;
                }
                for (int j = 0; j < bits[c]; j++) o.p[plane[c] + j * nb + g] = (uint8_t)x[j];
            }
        }
        zw_write(w, o.p, o.n, 0);
    }
    free(seen); free(idx); free(bits); free(plane); free(o.p);
}

static const char *pack_dec(const uint8_t *cp, size_t cn, Sink *s) {
    Dims d;
    uint64_t R;
    ZR z;
    zr_open(&z, cp, cn, 64);
    const char *err = get_header(&z, &d, &R);
    if (err) return err;
    if (R > (1u << 30) || d.cols > (1u << 24)) return "bad block size";
    uint64_t C = d.cols;
    size_t skip = z.pos, cap = C * (257 + 8 * ((R + 7) / 8)) + 64; // one whole block
    zr_close(&z);
    zr_open(&z, cp, cn, cap);
    if (zr_fill(&z, skip) < skip) return "truncated";
    z.pos = skip;
    uint8_t *out = alloc_rows(&d, R), *bits = malloc(C), *ks = malloc(C);
    size_t *at = malloc(C * sizeof *at); // offset of each column's [k-1] byte from z.pos
    if (!bits || !ks || !at) die("out of memory", NULL);
    for (uint64_t r0 = 0; r0 < d.rows && !err; r0 += R) {
        uint64_t rb = d.rows - r0 < R ? d.rows - r0 : R, nb = (rb + 7) / 8;
        size_t off = 0;
        for (uint64_t c = 0; c < C; c++) {
            if (zr_fill(&z, off + 1) < off + 1) { err = "truncated"; break; }
            int k = z.buf[z.pos + off] + 1;
            at[c] = off; ks[c] = (uint8_t)(k - 1); bits[c] = (uint8_t)nbits(k);
            off += 1 + k + bits[c] * nb;
        }
        if (err || zr_fill(&z, off) < off) { err = "truncated"; break; }
        const uint8_t *blk = z.buf + z.pos;
        for (uint64_t g = 0; g < nb && !err; g++) {
            uint8_t *t = out + g * 8 * d.stride;
            int cnt = rb - g * 8 < 8 ? (int)(rb - g * 8) : 8;
            for (uint64_t c = 0; c < C; c++) {
                const uint8_t *alpha = blk + at[c] + 1, *p = alpha + ks[c] + 1 + g;
                if (bits[c] == 0) { for (int i = 0; i < cnt; i++) t[i * d.stride + c] = alpha[0]; continue; }
                if (bits[c] == 1) { unsigned x = p[0]; for (int i = 0; i < cnt; i++) t[i * d.stride + c] = alpha[x >> i & 1]; continue; }
                unsigned x[8];
                for (int j = 0; j < bits[c]; j++) x[j] = p[j * nb];
                for (int i = 0; i < cnt; i++) {
                    unsigned v = 0;
                    for (int j = 0; j < bits[c]; j++) v |= (x[j] >> i & 1u) << j;
                    if (v > ks[c]) { err = "bad symbol index"; break; }
                    t[i * d.stride + c] = alpha[v];
                }
            }
        }
        z.pos += off;
        if (!err) sink_rows(s, out, &d, r0, rb);
    }
    if (!err && zr_fill(&z, 1)) err = "trailing data";
    zr_close(&z);
    free(out); free(bits); free(ks); free(at);
    return err;
}

// ---- zstd baseline
static void zstd_enc(const uint8_t *in, uint64_t n, ZW *w) {
    for (uint64_t off = 0; off < n; off += BLOCK) zw_write(w, in + off, (size_t)(n - off < BLOCK ? n - off : BLOCK), 0);
}

static const char *zstd_dec(const uint8_t *cp, size_t cn, Sink *s) {
    ZR r;
    zr_open(&r, cp, cn, BLOCK);
    while (zr_fill(&r, r.cap)) { sink(s, r.buf + r.pos, r.n - r.pos); r.pos = r.n; }
    zr_close(&r);
    return NULL;
}

// ---- dispatch
enum { M_ZSTD, M_TP, M_PACK };

static const char *MAGIC[3] = {NULL, "VTP1", "VPK1"};

static const char *encode(int m, const uint8_t *in, uint64_t n, int level, int lng, FILE *f, Buf *mem) {
    ZW w;
    Dims d;
    if (m != M_ZSTD) { const char *err = scan(in, n, &d); if (err) return err; }
    zw_open(&w, level, lng, f, mem);
    if (MAGIC[m]) zw_raw(&w, MAGIC[m], 4);
    if (m == M_ZSTD) zstd_enc(in, n, &w);
    else if (m == M_TP) tp_enc(in, &d, &w);
    else pack_enc(in, &d, &w);
    zw_close(&w);
    return NULL;
}

// The method comes from the magic; anything else must be a plain zstd frame.
static const char *decode(const uint8_t *cp, size_t cn, Sink *s) {
    if (!cn) return "empty compressed file"; // every valid output holds at least one zstd frame
    if (cn >= 4 && !memcmp(cp, MAGIC[M_TP], 4)) return tp_dec(cp + 4, cn - 4, s);
    if (cn >= 4 && !memcmp(cp, MAGIC[M_PACK], 4)) return pack_dec(cp + 4, cn - 4, s);
    return zstd_dec(cp, cn, s);
}

static const uint8_t *map_file(const char *path, uint64_t *n) {
    HANDLE f = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_FLAG_SEQUENTIAL_SCAN, NULL);
    if (f == INVALID_HANDLE_VALUE) die("cannot open ", path);
    LARGE_INTEGER sz;
    GetFileSizeEx(f, &sz);
    *n = (uint64_t)sz.QuadPart;
    if (!*n) { CloseHandle(f); return (const uint8_t *)""; }
    HANDLE m = CreateFileMappingA(f, NULL, PAGE_READONLY, 0, 0, NULL);
    const uint8_t *p = m ? MapViewOfFile(m, FILE_MAP_READ, 0, 0, 0) : NULL;
    if (!p) die("cannot map ", path);
    CloseHandle(m);
    CloseHandle(f);
    return p;
}

static double now(void) {
    LARGE_INTEGER t, f;
    QueryPerformanceCounter(&t);
    QueryPerformanceFrequency(&f);
    return (double)t.QuadPart / f.QuadPart;
}

static void selftest(void) {
    // CRLF + no final eol, LF, single line without eol, a column with 9 distinct bytes (4 planes), odd row counts
    const char *cases[] = {"0LX\r\n1H?\r\nL1H\r\nXLL", "0H\n1L\n", "X", "0\n1\n2\n3\n4\n5\n6\n7\n8\n0\n1\n", "01X\n11X\n0XX\n"};
    for (int R = 0; R <= 3; R += 3) {
        g_R = R; // 0 = default (one block), 3 = several blocks with a short last block
        for (int k = 0; k < 5; k++)
            for (int m = 0; m < 3; m++) {
                const char *in = cases[k];
                Buf b = {0};
                assert(!encode(m, (const uint8_t *)in, strlen(in), 3, 0, NULL, &b));
                Sink s = {NULL, (const uint8_t *)in, strlen(in), 0, 0};
                assert(!decode(b.p, b.n, &s) && s.off == strlen(in) && s.bad == 0);
                free(b.p);
            }
    }
    g_R = 0;
    Sink e = {0};
    assert(decode((const uint8_t *)"", 0, &e)); // empty .compr must be rejected
    Dims d;
    assert(scan((const uint8_t *)"01\n0\n1\n", 7, &d));
    assert(scan((const uint8_t *)"01\n0\n11\n", 8, &d));
    puts("selftest ok");
}

static FILE *open_out(const char *path) {
    FILE *f = fopen(path, "wb");
    if (!f) die("cannot create ", path);
    g_out_path = path; g_out_f = f;
    setvbuf(f, NULL, _IOFBF, 1u << 20);
    return f;
}

int main(int argc, char **argv) {
    if (argc > 1 && !strcmp(argv[1], "--selftest")) { selftest(); return 0; }
    uint64_t n, vec;
    const char *err;
    double t0 = now();
    if (argc == 6 && !strcmp(argv[1], "c")) {
        int lng = strstr(argv[2], "-long") != NULL, level = atoi(argv[3]);
        int m = !strncmp(argv[2], "tp", 2) ? M_TP : !strncmp(argv[2], "pack", 4) ? M_PACK : !strncmp(argv[2], "zstd", 4) ? M_ZSTD : -1;
        if (m < 0) die("unknown method ", argv[2]);
        const uint8_t *in = map_file(argv[4], &n);
        FILE *f = open_out(argv[5]);
        if ((err = encode(m, in, n, level, lng, f, NULL))) die("encode failed: ", err);
        g_out_f = NULL;
        if (fclose(f)) die("write failed: ", argv[5]);
        g_out_path = NULL;
        vec = n;
        map_file(argv[5], &n);
    } else if (argc == 4 && !strcmp(argv[1], "d")) {
        const uint8_t *cp = map_file(argv[2], &n);
        Sink s = {open_out(argv[3]), NULL, 0, 0, 0};
        if ((err = decode(cp, (size_t)n, &s))) die("decode failed: ", err);
        g_out_f = NULL;
        if (fclose(s.f)) die("write failed: ", argv[3]);
        g_out_path = NULL;
        vec = s.off;
    } else {
        fprintf(stderr, "usage: tries c <zstd|tp|pack>[-long] <level> <in.vec> <out.compr>\n       tries d <in.compr> <out.vec>\n       tries --selftest\n");
        return 2;
    }
    double t = now() - t0;
    printf("%s: %llu B .vec, %llu B .compr, %.3f s, %.1f MB/s (MB of .vec per second)\n", argv[1][0] == 'c' ? "compress" : "decompress",
           (unsigned long long)vec, (unsigned long long)n, t, vec / 1e6 / t);
    return 0;
}
