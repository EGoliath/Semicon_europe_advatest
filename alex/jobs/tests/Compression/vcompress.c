// vcompress: zstd baseline. Compresses a .vec file into vector_<level>.compr and verifies the round-trip.
// build: gcc -O2 vcompress.c -o vcompress.exe "%WINLIBS%\bin\libzstd.dll"   (libzstd.dll must be on PATH or next to the exe)
// run:   vcompress.exe <level> [input.vec] [outdir]     default input ..\001-contents\Vectors.vec, outdir "."
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>

// shortcut: hand-declared zstd 1.5 API (WinLibs ships libzstd.dll without zstd.h); use the official header if more API is needed.
size_t ZSTD_compress(void *dst, size_t cap, const void *src, size_t n, int level);
size_t ZSTD_decompress(void *dst, size_t cap, const void *src, size_t n);
size_t ZSTD_compressBound(size_t n);
unsigned ZSTD_isError(size_t code);
const char *ZSTD_getErrorName(size_t code);
int ZSTD_minCLevel(void);
int ZSTD_maxCLevel(void);
const char *ZSTD_versionString(void);

static double now(void) {
    LARGE_INTEGER t, f;
    QueryPerformanceCounter(&t);
    QueryPerformanceFrequency(&f);
    return (double)t.QuadPart / f.QuadPart;
}

int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: vcompress <level %d..%d> [input.vec] [outdir]\n", ZSTD_minCLevel(), ZSTD_maxCLevel()); return 2; }
    char *e;
    long level = strtol(argv[1], &e, 10);
    if (*e || e == argv[1] || level < ZSTD_minCLevel() || level > ZSTD_maxCLevel()) {
        fprintf(stderr, "level must be an integer in %d..%d\n", ZSTD_minCLevel(), ZSTD_maxCLevel());
        return 2;
    }
    const char *in = argc > 2 ? argv[2] : "..\\001-contents\\Vectors.vec", *dir = argc > 3 ? argv[3] : ".";

    // shortcut: whole file in RAM (input + compressed + verify copy, ~2x input), switch to ZSTD streaming API for files near RAM size.
    FILE *f = fopen(in, "rb");
    if (!f) { fprintf(stderr, "cannot open %s\n", in); return 1; }
    _fseeki64(f, 0, SEEK_END);
    size_t n = (size_t)_ftelli64(f);
    _fseeki64(f, 0, SEEK_SET);
    size_t cap = ZSTD_compressBound(n);
    char *src = malloc(n ? n : 1), *dst = malloc(cap), *back = malloc(n ? n : 1);
    if (!src || !dst || !back) { fprintf(stderr, "out of memory\n"); return 1; }
    if (fread(src, 1, n, f) != n) { fprintf(stderr, "read failed: %s\n", in); return 1; }
    fclose(f);

    double t0 = now();
    size_t c = ZSTD_compress(dst, cap, src, n, (int)level);
    double t1 = now();
    if (ZSTD_isError(c)) { fprintf(stderr, "compress failed: %s\n", ZSTD_getErrorName(c)); return 1; }
    size_t d = ZSTD_decompress(back, n, dst, c);
    double t2 = now();
    if (ZSTD_isError(d) || d != n || memcmp(src, back, n)) { fprintf(stderr, "ROUND-TRIP FAILED\n"); return 1; }

    char out[MAX_PATH];
    snprintf(out, sizeof out, "%s\\vector_%ld.compr", dir, level);
    f = fopen(out, "wb");
    if (!f || fwrite(dst, 1, c, f) != c || fclose(f)) { fprintf(stderr, "write failed: %s\n", out); return 1; }

    double mb = n / 1e6;
    printf("zstd %s  level %ld  %s -> %s\n", ZSTD_versionString(), level, in, out);
    printf("in %zu B  out %zu B  ratio %.3fx  compress %.1f MB/s (%.3f ms)  decompress %.1f MB/s (%.3f ms)  round-trip OK\n",
           n, c, c ? (double)n / c : 0, mb / (t1 - t0), (t1 - t0) * 1e3, mb / (t2 - t1), (t2 - t1) * 1e3);
    return 0;
}
