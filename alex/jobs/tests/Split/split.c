// split: drive/read column split + zstd per stream, benchmarked against whole-file zstd. Fully streaming: the input is
// memory-mapped and processed in row blocks, so memory use stays constant for multi-GB files.
//   Vectors.vec -> vectors_{map,drive,read,anomaly}_<level>.compr   (+ baseline_<level>.compr = plain zstd of the input)
// build: gcc -O2 split.c -o split.exe libzstd.dll          (libzstd.dll from WinLibs mingw64\bin, next to the exe)
// run:   split.exe [level=9] [input.vec] [outdir]          compress both ways, time decompression, verify byte-exactness
//        split.exe -x <level> <dir> <out.vec>               rebuild a .vec from the four part files in <dir>
//        split.exe --selftest
//
// Formats (each part is one zstd frame)
//   column type : drive if it holds at least as many 0/1 as L/H, else read (X-only columns count as drive).
//   drive/read  : one '\n'-terminated line per row with that row's cells of the stream's columns, in column order;
//                 anomaly cells are removed, so lines can differ in length.
//   anomaly     : a cell that is neither X nor of its column's type (any other byte too). One record per cell in
//                 row-major order: varint row delta, varint col (absolute on a new row, else delta), 1 byte char.
//                 Rebuild inserts them last, at their (row, col).
//   map         : varint cols, varint rows, byte eol length (0/1/2), byte last line has eol (0/1),
//                 byte first column type ('D'/'R'), then varint run lengths of alternating column types.
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
size_t ZSTD_decompressStream(ZSTD_DCtx *, ZSTD_outBuffer *, ZSTD_inBuffer *);
unsigned ZSTD_isError(size_t code);
const char *ZSTD_getErrorName(size_t code);
int ZSTD_minCLevel(void);
int ZSTD_maxCLevel(void);
#define ZSTD_c_compressionLevel 100
#define ZSTD_e_continue 0
#define ZSTD_e_end 2

#define BLOCK (4u << 20) // bytes of input rows per split block / output bytes per rebuild flush

typedef struct { uint8_t *p; size_t n, cap; } Buf;

static void die(const char *msg, const char *arg) { fprintf(stderr, "%s%s\n", msg, arg ? arg : ""); exit(1); }

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

// ---- zstd stream writer: to a FILE, or appended to a Buf when f == NULL
typedef struct { ZSTD_CCtx *c; FILE *f; Buf *mem; uint8_t *out; size_t cap; uint64_t total; } ZW;

static void zw_open(ZW *w, int level, FILE *f, Buf *mem) {
    w->c = ZSTD_createCCtx();
    w->f = f; w->mem = mem; w->total = 0;
    w->cap = ZSTD_CStreamOutSize();
    w->out = malloc(w->cap);
    if (!w->c || !w->out) die("out of memory", NULL);
    ZSTD_CCtx_setParameter(w->c, ZSTD_c_compressionLevel, level);
}

static void zw_write(ZW *w, const void *p, size_t n, int end) {
    ZSTD_inBuffer in = {p, n, 0};
    for (;;) {
        ZSTD_outBuffer o = {w->out, w->cap, 0};
        size_t r = ZSTD_compressStream2(w->c, &o, &in, end ? ZSTD_e_end : ZSTD_e_continue);
        if (ZSTD_isError(r)) die("compress failed: ", ZSTD_getErrorName(r));
        if (o.pos) {
            if (w->f) { if (fwrite(w->out, 1, o.pos, w->f) != o.pos) die("write failed", NULL); }
            else { reserve(w->mem, o.pos); memcpy(w->mem->p + w->mem->n, w->out, o.pos); w->mem->n += o.pos; }
            w->total += o.pos;
        }
        if (end ? r == 0 : in.pos == in.size) return;
    }
}

static void zw_close(ZW *w) { zw_write(w, NULL, 0, 1); ZSTD_freeCCtx(w->c); free(w->out); }

// ---- zstd stream reader over a compressed buffer in memory (or memory-mapped)
typedef struct { ZSTD_DCtx *d; ZSTD_inBuffer in; uint8_t *buf; size_t n, pos, cap; int done; } ZR;

static void zr_open(ZR *r, const uint8_t *p, size_t n, size_t cap) {
    r->d = ZSTD_createDCtx();
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
        if (r->in.pos == r->in.size && (ret == 0 || o.pos < o.size)) r->done = 1; // end, or truncated (caught by caller)
    }
    return r->n - r->pos;
}

static void zr_close(ZR *r) { ZSTD_freeDCtx(r->d); free(r->buf); }

// ---- output sink: write to a file, compare against the original, or discard (timing only)
typedef struct { FILE *f; const uint8_t *ref; uint64_t refn, off, bad; } Sink;

static void sink(Sink *s, const uint8_t *p, size_t n) {
    if (s->f && fwrite(p, 1, n, s->f) != n) die("write failed", NULL);
    if (s->ref) {
        size_t m = s->off >= s->refn ? 0 : (size_t)(s->refn - s->off < n ? s->refn - s->off : n);
        if (m < n) s->bad += n - m; // output longer than the original
        if (memcmp(s->ref + s->off, p, m))
            for (size_t i = 0; i < m; i++) s->bad += s->ref[s->off + i] != p[i];
    }
    s->off += n;
}

static uint8_t g_ok[2][256]; // g_ok[is_drive_column][byte]: byte belongs in that column's stream

static void init_ok(void) {
    g_ok[0]['X'] = g_ok[1]['X'] = 1;
    g_ok[1]['0'] = g_ok[1]['1'] = 1;
    g_ok[0]['L'] = g_ok[0]['H'] = 1;
}

typedef struct { uint64_t cols, rows, stride; int eol, final; uint8_t *type; } Dims;

// Pass 1: validates fixed-width lines and decides each column's type by majority. NULL on success, else an error.
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

    uint64_t *cnt = calloc(d->cols * 2, sizeof *cnt); // [read, drive] per column
    if (!cnt || !(d->type = malloc(d->cols))) return "out of memory";
    for (uint64_t r = 0; r < d->rows; r++) {
        const uint8_t *line = in + r * d->stride;
        if (r + 1 < d->rows || d->final) {
            const uint8_t *e = line + d->cols;
            if (d->eol == 1 ? e[0] != '\n' : (e[0] != '\r' || e[1] != '\n')) { free(cnt); return "lines are not all the same width / line ending"; }
        }
        for (uint64_t c = 0; c < d->cols; c++) {
            uint8_t ch = line[c];
            cnt[2 * c] += ch == 'L' || ch == 'H';
            cnt[2 * c + 1] += ch == '0' || ch == '1';
        }
    }
    for (uint64_t c = 0; c < d->cols; c++) d->type[c] = cnt[2 * c + 1] >= cnt[2 * c];
    free(cnt);
    return NULL;
}

// Splits into the four writers (0 map, 1 drive, 2 read, 3 anomaly); the caller opens and closes them.
static const char *split(const uint8_t *in, uint64_t n, ZW w[4], uint64_t *nanom) {
    Dims d;
    const char *err = scan(in, n, &d);
    if (err) return err;

    Buf map = {0};
    putv(&map, d.cols); putv(&map, d.rows); put(&map, (uint8_t)d.eol); put(&map, (uint8_t)d.final);
    put(&map, d.type[0] ? 'D' : 'R');
    uint64_t nd = 0;
    for (uint64_t c = 0, run = 0; c < d.cols; c++) {
        nd += d.type[c];
        if (++run, c + 1 == d.cols || d.type[c + 1] != d.type[c]) { putv(&map, run); run = 0; }
    }
    zw_write(&w[0], map.p, map.n, 0);
    free(map.p);

    uint64_t rpb = BLOCK / d.stride ? BLOCK / d.stride : 1;
    Buf b[3] = {{0}}; // read, drive, anomaly (index = column type for the first two)
    reserve(&b[0], rpb * (d.cols - nd + 1));
    reserve(&b[1], rpb * (nd + 1));
    uint64_t prow = 0, pcol = 0;
    int any = 0;
    *nanom = 0;
    for (uint64_t r0 = 0; r0 < d.rows; r0 += rpb) {
        uint64_t r1 = r0 + rpb < d.rows ? r0 + rpb : d.rows;
        uint8_t *op[2] = {b[0].p, b[1].p};
        for (uint64_t r = r0; r < r1; r++) {
            const uint8_t *line = in + r * d.stride;
            for (uint64_t c = 0; c < d.cols; c++) {
                uint8_t ch = line[c], t = d.type[c];
                if (g_ok[t][ch]) { *op[t]++ = ch; continue; }
                putv(&b[2], r - prow);
                putv(&b[2], (r == prow && any) ? c - pcol : c);
                put(&b[2], ch);
                prow = r; pcol = c; any = 1;
                (*nanom)++;
            }
            *op[0]++ = '\n';
            *op[1]++ = '\n';
        }
        zw_write(&w[2], b[0].p, op[0] - b[0].p, 0);
        zw_write(&w[1], b[1].p, op[1] - b[1].p, 0);
        zw_write(&w[3], b[2].p, b[2].n, 0);
        b[2].n = 0;
    }
    for (int i = 0; i < 3; i++) free(b[i].p);
    free(d.type);
    return NULL;
}

typedef struct { uint64_t row, col; int any; uint8_t ch; } Anom; // anomaly decoder cursor

// Mirrors the encoder: col is a delta only when the row delta is 0 and a previous anomaly exists.
// Returns 1 = next anomaly in *a, 0 = no more, -1 = corrupt.
static int next_anomaly(ZR *z, Anom *a) {
    uint64_t dr, dc;
    if (!zr_fill(z, 21)) return 0; // 2 varints (max 10 B each) + 1 char
    size_t i = z->pos;
    if (!getv(z->buf, z->n, &i, &dr) || !getv(z->buf, z->n, &i, &dc) || i >= z->n) return -1;
    a->col = (dr == 0 && a->any) ? a->col + dc : dc;
    a->row += dr;
    a->ch = z->buf[i++];
    a->any = 1;
    z->pos = i;
    return 1;
}

// Rebuilds the original from the four compressed parts (0 map, 1 drive, 2 read, 3 anomaly) into the sink.
// Anomalies are inserted last, at their recorded (row, col). NULL on success, else an error.
static const char *rebuild(const uint8_t *cp[4], const size_t cn[4], Sink *s) {
    ZR zm;
    zr_open(&zm, cp[0], cn[0], 1u << 20);
    size_t mn = zr_fill(&zm, 1u << 20), i = 0;
    if (!zm.done) return "map too large";
    uint64_t cols, rows, run;
    if (!getv(zm.buf, mn, &i, &cols) || !getv(zm.buf, mn, &i, &rows) || !cols || i + 3 > mn) return "bad map header";
    int eol = zm.buf[i++], final = zm.buf[i++];
    uint8_t t = zm.buf[i++] == 'D';
    if (eol > 2) return "bad map eol";
    uint64_t *rl = malloc(cols * sizeof *rl), nruns = 0, cnt[2] = {0};
    uint8_t *rt = malloc(cols);
    if (!rl || !rt) return "out of memory";
    for (uint64_t c = 0; c < cols; c += run, t ^= 1) {
        if (!getv(zm.buf, mn, &i, &run) || !run || run > cols - c) return "bad map runs";
        rl[nruns] = run; rt[nruns++] = t; cnt[t] += run;
    }
    zr_close(&zm);

    ZR z[2], za; // z[0] read stream, z[1] drive stream
    zr_open(&z[0], cp[2], cn[2], BLOCK + 2 * (cnt[0] + 1));
    zr_open(&z[1], cp[1], cn[1], BLOCK + 2 * (cnt[1] + 1));
    zr_open(&za, cp[3], cn[3], 1u << 16);
    Buf out = {0};
    reserve(&out, BLOCK + cols + 2);
    Anom a = {0};
    int have = next_anomaly(&za, &a);
    if (have < 0) return "bad anomaly record";
    const char *err = NULL;

    for (uint64_t r = 0; r < rows && !err; r++) {
        zr_fill(&z[0], cnt[0] + 1);
        zr_fill(&z[1], cnt[1] + 1);
        const uint8_t *sp[2] = {z[0].buf + z[0].pos, z[1].buf + z[1].pos}, *se[2] = {z[0].buf + z[0].n, z[1].buf + z[1].n};
        uint8_t *o = out.p + out.n;
        if (!have || a.row != r) { // fast path: no anomaly in this row, copy whole column runs
            if (se[0] - sp[0] <= (ptrdiff_t)cnt[0] || sp[0][cnt[0]] != '\n' || se[1] - sp[1] <= (ptrdiff_t)cnt[1] || sp[1][cnt[1]] != '\n') {
                err = "stream line has wrong length";
                break;
            }
            for (uint64_t k = 0; k < nruns; k++) { memcpy(o, sp[rt[k]], rl[k]); o += rl[k]; sp[rt[k]] += rl[k]; }
        } else {
            for (uint64_t k = 0, c = 0; k < nruns && !err; k++)
                for (uint64_t j = 0; j < rl[k]; j++, c++) {
                    if (have && a.row == r && a.col == c) {
                        *o++ = a.ch;
                        if ((have = next_anomaly(&za, &a)) < 0) err = "bad anomaly record";
                    } else if (sp[rt[k]] >= se[rt[k]] || *sp[rt[k]] == '\n') {
                        err = "stream line too short";
                        break;
                    } else *o++ = *sp[rt[k]]++;
                }
            if (err) break;
        }
        if (sp[0] >= se[0] || *sp[0]++ != '\n' || sp[1] >= se[1] || *sp[1]++ != '\n') { err = "stream line too long"; break; }
        z[0].pos = sp[0] - z[0].buf;
        z[1].pos = sp[1] - z[1].buf;
        if (r + 1 < rows || final) {
            if (eol == 2) *o++ = '\r';
            if (eol) *o++ = '\n';
        }
        out.n = o - out.p;
        if (out.n >= BLOCK) { sink(s, out.p, out.n); out.n = 0; }
    }
    if (!err) {
        sink(s, out.p, out.n);
        if (have || zr_fill(&z[0], 1) || zr_fill(&z[1], 1)) err = "leftover stream or anomaly data";
    }
    zr_close(&z[0]); zr_close(&z[1]); zr_close(&za);
    free(out.p); free(rl); free(rt);
    return err;
}

// ---- baseline: plain zstd of the whole input, streamed
static uint64_t base_compress(const uint8_t *in, uint64_t n, int level, FILE *f) {
    ZW w;
    zw_open(&w, level, f, NULL);
    for (uint64_t off = 0; off < n; off += BLOCK) zw_write(&w, in + off, (size_t)(n - off < BLOCK ? n - off : BLOCK), 0);
    zw_close(&w);
    return w.total;
}

static void base_decompress(const uint8_t *cp, size_t cn, Sink *s) {
    ZR r;
    zr_open(&r, cp, cn, BLOCK);
    while (zr_fill(&r, r.cap)) { sink(s, r.buf + r.pos, r.n - r.pos); r.pos = r.n; }
    zr_close(&r);
}

// ---- files
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
    CloseHandle(m); // the view keeps the mapping alive
    CloseHandle(f);
    return p;
}

static FILE *open_out(const char *path) {
    FILE *f = fopen(path, "wb");
    if (!f) die("cannot create ", path);
    return f;
}

static const char *PART[4] = {"map", "drive", "read", "anomaly"};

static double now(void) {
    LARGE_INTEGER t, f;
    QueryPerformanceCounter(&t);
    QueryPerformanceFrequency(&f);
    return (double)t.QuadPart / f.QuadPart;
}

static void selftest(void) {
    // col 0 drive with an L anomaly, col 1 read with a 1 anomaly, col 2 read with an unknown '?'; CRLF, no final newline.
    // Anomalies (1,2) (2,0) (2,1) exercise both the new-row and same-row column encodings.
    const char *cases[] = {"0LX\r\n1H?\r\nL1H\r\nXLL", "0H\n1L\n", "X\n"};
    for (int k = 0; k < 3; k++) {
        const char *in = cases[k];
        Buf mem[4] = {{0}};
        ZW w[4];
        uint64_t na;
        for (int i = 0; i < 4; i++) zw_open(&w[i], 3, NULL, &mem[i]);
        assert(!split((const uint8_t *)in, strlen(in), w, &na));
        for (int i = 0; i < 4; i++) zw_close(&w[i]);
        assert(na == (k == 0 ? 3u : 0u));
        const uint8_t *cp[4];
        size_t cn[4];
        for (int i = 0; i < 4; i++) { cp[i] = mem[i].p; cn[i] = mem[i].n; }
        Sink s = {NULL, (const uint8_t *)in, strlen(in), 0, 0};
        assert(!rebuild(cp, cn, &s) && s.off == strlen(in) && s.bad == 0);
    }
    Dims d;
    assert(scan((const uint8_t *)"01\n0\n1\n", 7, &d)); // size does not fit fixed-width lines
    assert(scan((const uint8_t *)"01\n0\n11\n", 8, &d)); // wrong line ending position
    // Sink counts differing bytes
    Sink s = {NULL, (const uint8_t *)"abcd", 4, 0, 0};
    sink(&s, (const uint8_t *)"abXd", 4);
    assert(s.bad == 1);
    puts("selftest ok");
}

static int parse_level(const char *s) {
    char *e;
    long l = strtol(s, &e, 10);
    if (*e || e == s || l < ZSTD_minCLevel() || l > ZSTD_maxCLevel()) {
        fprintf(stderr, "level must be an integer in %d..%d\n", ZSTD_minCLevel(), ZSTD_maxCLevel());
        exit(2);
    }
    return (int)l;
}

int main(int argc, char **argv) {
    init_ok();
    if (argc > 1 && !strcmp(argv[1], "--selftest")) { selftest(); return 0; }
    char path[MAX_PATH];
    const uint8_t *cp[4];
    size_t cn[4];
    uint64_t n64;

    if (argc > 1 && !strcmp(argv[1], "-x")) {
        if (argc != 5) { fprintf(stderr, "usage: split -x <level> <dir> <out.vec>\n"); return 2; }
        int level = parse_level(argv[2]);
        for (int i = 0; i < 4; i++) {
            snprintf(path, sizeof path, "%s\\vectors_%s_%d.compr", argv[3], PART[i], level);
            cp[i] = map_file(path, &n64);
            cn[i] = (size_t)n64;
        }
        Sink s = {open_out(argv[4]), NULL, 0, 0, 0};
        const char *err = rebuild(cp, cn, &s);
        if (err) die("rebuild failed: ", err);
        if (fclose(s.f)) die("write failed: ", argv[4]);
        printf("rebuilt %s (%llu B)\n", argv[4], (unsigned long long)s.off);
        return 0;
    }

    int level = argc > 1 ? parse_level(argv[1]) : 9;
    const char *inpath = argc > 2 ? argv[2] : "..\\001-contents\\Vectors.vec", *dir = argc > 3 ? argv[3] : ".";
    uint64_t n;
    const uint8_t *in = map_file(inpath, &n);
    double mb = n / 1e6;

    // baseline: whole-file zstd
    snprintf(path, sizeof path, "%s\\baseline_%d.compr", dir, level);
    FILE *bf = open_out(path);
    double t0 = now();
    uint64_t bsize = base_compress(in, n, level, bf);
    double t1 = now();
    if (fclose(bf)) die("write failed: ", path);

    // split
    ZW w[4];
    FILE *pf[4];
    for (int i = 0; i < 4; i++) {
        snprintf(path, sizeof path, "%s\\vectors_%s_%d.compr", dir, PART[i], level);
        zw_open(&w[i], level, pf[i] = open_out(path), NULL);
    }
    uint64_t na;
    double t2 = now();
    const char *err = split(in, n, w, &na);
    if (err) die("split failed: ", err);
    for (int i = 0; i < 4; i++) zw_close(&w[i]);
    double t3 = now();
    uint64_t ssize = 0;
    for (int i = 0; i < 4; i++) {
        if (fclose(pf[i])) die("write failed", NULL);
        snprintf(path, sizeof path, "%s\\vectors_%s_%d.compr", dir, PART[i], level);
        cp[i] = map_file(path, &n64);
        cn[i] = (size_t)n64;
        ssize += n64;
    }
    snprintf(path, sizeof path, "%s\\baseline_%d.compr", dir, level);
    const uint8_t *bp = map_file(path, &n64);

    // decompression timing (output discarded), then a separate verification pass against the original
    Sink sb = {0}, ss = {0};
    double t4 = now();
    base_decompress(bp, (size_t)bsize, &sb);
    double t5 = now();
    if ((err = rebuild(cp, cn, &ss))) die("rebuild failed: ", err);
    double t6 = now();
    Sink vb = {NULL, in, n, 0, 0}, vs = {NULL, in, n, 0, 0};
    base_decompress(bp, (size_t)bsize, &vb);
    if ((err = rebuild(cp, cn, &vs))) die("rebuild failed: ", err);
    uint64_t lb = vb.bad + (vb.off < n ? n - vb.off : 0), ls = vs.bad + (vs.off < n ? n - vs.off : 0);

    printf("input %s  %llu B  zstd level %d  (%llu anomalies)\n", inpath, (unsigned long long)n, level, (unsigned long long)na);
    printf("  %-9s %12s %9s %12s %12s %14s\n", "method", "size B", "ratio", "compr MB/s", "decomp MB/s", "lost bytes");
    printf("  %-9s %12llu %8.2fx %12.1f %12.1f %14llu\n", "zstd", (unsigned long long)bsize, (double)n / bsize, mb / (t1 - t0), mb / (t5 - t4), (unsigned long long)lb);
    printf("  %-9s %12llu %8.2fx %12.1f %12.1f %14llu\n", "split", (unsigned long long)ssize, (double)n / ssize, mb / (t3 - t2), mb / (t6 - t5), (unsigned long long)ls);
    printf("  parts:");
    for (int i = 0; i < 4; i++) printf(" %s %zu B", PART[i], cn[i]);
    printf("\n  split vs zstd: %.3fx smaller, decompression %.2fx the speed\n", (double)bsize / ssize, (t5 - t4) / (t6 - t5));
    printf("CSV,%s,%llu,%d,%llu,%llu,%.1f,%.1f,%.1f,%.1f,%llu,%llu,%llu\n", inpath, (unsigned long long)n, level,
           (unsigned long long)bsize, (unsigned long long)ssize, mb / (t1 - t0), mb / (t3 - t2), mb / (t5 - t4), mb / (t6 - t5),
           (unsigned long long)lb, (unsigned long long)ls, (unsigned long long)na);
    return lb || ls;
}
