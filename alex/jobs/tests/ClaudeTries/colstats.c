// colstats: per-column symbol mix and entropy (order-0, and given the 8 cells above), to see where the bits are.
// build: gcc -O2 colstats.c -o colstats.exe     run: colstats.exe <in.vec> [max_MB=100]
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static int sym(int c) { return c == '0' ? 0 : c == '1' ? 1 : c == 'X' ? 2 : 3; }
static double H(const uint32_t *h, int n) { double t = 0, b = 0; for (int i = 0; i < n; i++) t += h[i]; for (int i = 0; i < n; i++) if (h[i]) b -= h[i] * log2(h[i] / t); return b; }
int main(int argc, char **argv) {
    FILE *f = fopen(argv[1], "rb");
    size_t max = (size_t)(argc > 2 ? atof(argv[2]) : 100) * 1000000;
    uint8_t *p = malloc(max);
    size_t n = fread(p, 1, max, f), cols = (uint8_t *)memchr(p, '\n', n) - p, stride = cols + 1, rows = n / stride;
    uint32_t *c0 = calloc(cols * 4, 4), *c8 = calloc(cols * 65536 * 4, 4);
    for (size_t c = 0; c < cols; c++) {
        unsigned hist = 0;
        for (size_t r = 0; r < rows; r++) {
            int s = sym(p[r * stride + c]);
            c0[c * 4 + s]++;
            c8[(c * 65536 + hist) * 4 + s]++;
            hist = (hist << 2 | s) & 0xFFFF;
        }
    }
    double t0 = 0, t8 = 0;
    printf("col  %%0    %%1    %%X   H0 bit/cell  H|8up\n");
    for (size_t c = 0; c < cols; c++) {
        double h0 = H(c0 + c * 4, 4) / rows, h8 = 0;
        for (int k = 0; k < 65536; k++) h8 += H(c8 + (c * 65536 + k) * 4, 4);
        h8 /= rows; t0 += h0; t8 += h8;
        printf("%3zu %5.1f %5.1f %5.1f   %.4f   %.4f\n", c, 100.0 * c0[c * 4] / rows, 100.0 * c0[c * 4 + 1] / rows, 100.0 * c0[c * 4 + 2] / rows, h0, h8);
    }
    printf("sum of H0 %.2f bit/row, H|8up %.2f bit/row (row = %zu cells)\n", t0, t8, cols);
    return 0;
}
