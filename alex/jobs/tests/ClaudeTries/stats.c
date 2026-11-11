// stats: empirical conditional entropy of a .vec under several cell contexts (static two-pass estimate,
// ignores model cost) + how often a row repeats an earlier row at distance p. Tells which model is worth building.
// build: gcc -O2 stats.c -o stats.exe     run: stats.exe <in.vec> [max_MB=256]
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int sym(int c) { switch (c) { case '0': return 0; case '1': return 1; case 'X': return 2; case 'L': return 3; case 'H': return 4; default: return 5; } }

#define NCTX 6
static const char *NAME[NCTX] = {"order0/pin", "|up", "|up,up2", "|up,left", "|up,up2,left,upleft", "|up..up4"};

int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: stats <in.vec> [max_MB]\n"); return 2; }
    FILE *f = fopen(argv[1], "rb");
    if (!f) { perror(argv[1]); return 1; }
    size_t max = (size_t)(argc > 2 ? atof(argv[2]) : 256) * 1000000;
    uint8_t *p = malloc(max);
    size_t n = fread(p, 1, max, f);
    fclose(f);
    uint8_t *nl = memchr(p, '\n', n);
    if (!nl) return 1;
    size_t cols = nl - p, stride = cols + 1, rows = n / stride; // shortcut: LF only, whole rows only
    uint32_t *cnt = calloc((size_t)NCTX * cols * 4096 * 8, 4);
    uint64_t same[65] = {0}, symc[8] = {0};
    for (size_t r = 0; r < rows; r++) {
        const uint8_t *L = p + r * stride;
        for (size_t c = 0; c < cols; c++) {
            int s = sym(L[c]);
            symc[s]++;
            int u1 = r > 0 ? sym(L[c - stride]) : 7, u2 = r > 1 ? sym(L[c - 2 * stride]) : 7;
            int u3 = r > 2 ? sym(L[c - 3 * stride]) : 7, u4 = r > 3 ? sym(L[c - 4 * stride]) : 7;
            int le = c > 0 ? sym(L[c - 1]) : 7, ul = r > 0 && c > 0 ? sym(L[c - 1 - stride]) : 7;
            int ctx[NCTX] = {0, u1, u1 | u2 << 3, u1 | le << 3, u1 | u2 << 3 | le << 6 | ul << 9, u1 | u2 << 3 | u3 << 6 | u4 << 9};
            for (int k = 0; k < NCTX; k++) cnt[(((size_t)k * cols + c) * 4096 + ctx[k]) * 8 + s]++;
        }
        for (int d = 1; d <= 64 && (size_t)d <= r; d++) same[d] += !memcmp(L, L - d * stride, cols);
    }
    double cells = (double)rows * cols;
    printf("%s: %zu rows x %zu pins (first %.0f MB)\n  symbols 0/1/X/L/H/other: %.3f %.3f %.3f %.3f %.3f %.3f\n", argv[1], rows, cols, n / 1e6,
           symc[0] / cells, symc[1] / cells, symc[2] / cells, symc[3] / cells, symc[4] / cells, symc[5] / cells);
    for (int k = 0; k < NCTX; k++) {
        double bits = 0;
        for (size_t i = 0; i < cols * 4096; i++) {
            uint32_t *h = cnt + ((size_t)k * cols * 4096 + i) * 8, t = 0;
            for (int s = 0; s < 8; s++) t += h[s];
            for (int s = 0; s < 8; s++) if (h[s]) bits -= h[s] * log2((double)h[s] / t);
        }
        printf("  %-22s %.4f bit/cell  -> %6.2fx vs raw file\n", NAME[k], bits / cells, n * 8.0 / bits);
    }
    printf("  row == row-d (fraction):");
    for (int d = 1; d <= 64; d++) if (same[d] * 50 > rows || d <= 4) printf(" d%d=%.3f", d, (double)same[d] / (rows - d));
    printf("\n");
    return 0;
}
