// lfsr: Berlekamp-Massey linear complexity of single columns (bit = cell=='1').
// A truly random sequence of N bits has linear complexity ~N/2; an LFSR output has much less.
// build: gcc -O2 lfsr.c -o lfsr.exe     run: lfsr.exe <in.vec> <N bits> <start row> <col>...
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static int bm(const uint8_t *s, int n) {
    uint8_t *c = calloc(n + 1, 1), *b = calloc(n + 1, 1), *t = malloc(n + 1);
    int L = 0, m = -1;
    c[0] = b[0] = 1;
    for (int i = 0; i < n; i++) {
        int d = s[i];
        for (int j = 1; j <= L; j++) d ^= c[j] & s[i - j];
        if (!d) continue;
        memcpy(t, c, n + 1);
        for (int j = 0; j + i - m <= n; j++) c[j + i - m] ^= b[j];
        if (2 * L <= i) { L = i + 1 - L; m = i; memcpy(b, t, n + 1); }
    }
    free(c); free(b); free(t);
    return L;
}
int main(int argc, char **argv) {
    FILE *f = fopen(argv[1], "rb");
    int N = atoi(argv[2]);
    long start = atol(argv[3]);
    char line[4096];
    if (!fgets(line, sizeof line, f)) return 1;
    long stride = (long)strlen(line);
    _fseeki64(f, (long long)start * stride, SEEK_SET);
    uint8_t *rows = malloc((size_t)N * stride);
    if (fread(rows, stride, N, f) != (size_t)N) return 1;
    uint8_t *s = malloc(N);
    for (int a = 4; a < argc; a++) {
        int col = atoi(argv[a]);
        for (int i = 0; i < N; i++) s[i] = rows[(size_t)i * stride + col] == '1';
        printf("col %d rows %ld..+%d: linear complexity %d (random ~%d)\n", col, start, N, bm(s, N), N / 2);
    }
    return 0;
}
