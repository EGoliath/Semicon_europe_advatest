// vecview: interactive pin x cycle viewer for Vectors.vec (Win32 GDI, no dependencies).
// The file is memory-mapped and only visible pixels are sampled, so cost per frame is O(window), not O(file).
// build: gcc -O2 vecview.c -o vecview.exe -lgdi32 libzstd.dll   (libzstd.dll from WinLibs mingw64\bin, next to the exe)
// run:   vecview.exe <Vectors.vec | vector_N.compr> [row:num,row:num,...]   |  vecview.exe --selftest
//        .compr (zstd) is decompressed to a self-deleting temp file and mapped; C toggles the literal/match overlay
//        optional 2nd arg = instruction blocks (yellow, with number) drawn in a gutter left of pin 0
// keys:  wheel = zoom at cursor, left-drag = pan, arrows = pan, +/- = zoom, F/Home = fit, Esc = quit
//        Backspace / mouse back = view history back, Shift+Backspace / mouse forward = history forward
//        C = toggle compression overlay (.compr only)
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <windowsx.h>
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define BG 0x303030u     // outside the grid; not black because black is a data color
#define INSTR 0xFFD700u  // instruction blocks
#define LITERAL 0x00FFFFu // overlay: byte zstd stored as a literal
#define HDR 62           // header bar height in pixels
#define HIST 256         // view history depth per direction
#define CHUNK (16u << 20) // overlay analysis chunk; bounds the sequence buffer to ~90 MB

typedef struct { double scale, ox, oy; } View; // screen pixels per cell; cell coords at grid top-left
typedef struct { uint64_t row, num; } Instr;

// shortcut: hand-declared zstd 1.5 API (WinLibs ships libzstd.dll without zstd.h); use the official header if more API is needed.
typedef struct ZSTD_CCtx_s ZSTD_CCtx;
typedef struct ZSTD_DCtx_s ZSTD_DCtx;
typedef struct { unsigned offset, litLength, matchLength, rep; } ZSTD_Sequence;
typedef struct { const void *src; size_t size, pos; } ZSTD_inBuffer;
typedef struct { void *dst; size_t size, pos; } ZSTD_outBuffer;
ZSTD_CCtx *ZSTD_createCCtx(void);
size_t ZSTD_CCtx_setParameter(ZSTD_CCtx *, int param, int value);
size_t ZSTD_sequenceBound(size_t n);
size_t ZSTD_generateSequences(ZSTD_CCtx *, ZSTD_Sequence *out, size_t cap, const void *src, size_t n);
ZSTD_DCtx *ZSTD_createDStream(void);
size_t ZSTD_decompressStream(ZSTD_DCtx *, ZSTD_outBuffer *, ZSTD_inBuffer *);
size_t ZSTD_DStreamOutSize(void);
unsigned ZSTD_isError(size_t);
const char *ZSTD_getErrorName(size_t);
#define ZSTD_c_compressionLevel 100

static uint64_t g_csize;              // compressed size, 0 = plain .vec
static int g_level, g_overlay;        // level used for the overlay re-run; overlay on/off
static uint8_t *g_mask;               // 1 bit per byte: 1 = literal, 0 = match
static volatile LONG64 g_done, g_lits; // bytes analysed so far, literal bytes among them
static HWND g_hwnd;

static const uint8_t *g_data;
static uint64_t g_size, g_cols, g_rows, g_stride;
static uint32_t g_lut[256];
static View g_v, g_back[HIST], g_fwd[HIST];
static int g_nback, g_nfwd;
static DWORD g_lastmove; // tick of last continuous nav (wheel/keys), to coalesce history entries
static Instr *g_instr;
static size_t g_ninstr;
static uint32_t *g_px;
static HBITMAP g_bmp;
static HDC g_memdc;
static int g_w, g_h, g_gh, *g_colmap; // g_gh: grid height (below header); g_colmap: screen x -> column, -1 = none
static int g_drag, g_mx, g_my;
static char g_name[MAX_PATH];

// shortcut: checks only the first line and the total size; a variable-width file whose size happens to fit renders garbled, add a full newline scan if such files appear.
static int parse_dims(const uint8_t *p, uint64_t n, uint64_t *cols, uint64_t *stride, uint64_t *rows) {
    if (n == 0) return 0;
    const uint8_t *nl = memchr(p, '\n', (size_t)n);
    if (!nl) { *cols = *stride = n; *rows = 1; return 1; }
    uint64_t eol = (nl > p && nl[-1] == '\r') ? 2 : 1;
    *cols = (uint64_t)(nl - p) + 1 - eol;
    *stride = *cols + eol;
    if (*cols == 0) return 0;
    uint64_t rem = n % *stride; // last line may lack its newline
    if (rem != 0 && rem != *cols) return 0;
    *rows = n / *stride + (rem != 0);
    return 1;
}

// shortcut: placeholder "row:num,row:num" input until the real instruction source is defined.
static size_t parse_instr(const char *s, Instr **out) {
    size_t cap = 1, n = 0;
    for (const char *p = s; *p; p++) cap += *p == ',';
    *out = malloc(cap * sizeof **out);
    while (*s) {
        char *e;
        uint64_t row = strtoull(s, &e, 10);
        if (e == s || *e != ':') return n;
        s = e + 1;
        uint64_t num = strtoull(s, &e, 10);
        if (e == s) return n;
        (*out)[n++] = (Instr){row, num};
        s = *e == ',' ? e + 1 : e;
        if (*e && *e != ',') return n;
    }
    return n;
}

// Each sequence = litLength literal bytes then matchLength match bytes; sets mask bits for literals from byte pos.
static uint64_t mark_sequences(const ZSTD_Sequence *s, size_t ns, uint8_t *mask, uint64_t pos) {
    uint64_t lits = 0;
    for (size_t i = 0; i < ns; i++) {
        for (unsigned k = 0; k < s[i].litLength; k++, pos++) mask[pos >> 3] |= (uint8_t)(1u << (pos & 7));
        lits += s[i].litLength;
        pos += s[i].matchLength;
    }
    return lits;
}

static int is_literal(uint64_t pos) { return (g_mask[pos >> 3] >> (pos & 7)) & 1; }

// Background thread: re-runs the zstd match finder at g_level and records which bytes end up as literals.
// shortcut: this re-simulates compression (not decoded from the .compr) and restarts per 16 MB chunk, so matches
// crossing a chunk boundary are lost; write a zstd sequence-section decoder if the exact per-file split is needed.
static DWORD WINAPI analyse(void *arg) {
    (void)arg;
    ZSTD_CCtx *cc = ZSTD_createCCtx();
    ZSTD_CCtx_setParameter(cc, ZSTD_c_compressionLevel, g_level);
    size_t cap = ZSTD_sequenceBound(CHUNK);
    ZSTD_Sequence *seq = malloc(cap * sizeof *seq);
    if (!cc || !seq) return 1;
    for (uint64_t base = 0; base < g_size; base += CHUNK) {
        size_t len = (size_t)(g_size - base < CHUNK ? g_size - base : CHUNK);
        size_t ns = ZSTD_generateSequences(cc, seq, cap, g_data + base, len);
        if (ZSTD_isError(ns)) { fprintf(stderr, "overlay stopped: %s\n", ZSTD_getErrorName(ns)); break; }
        InterlockedAdd64(&g_lits, (LONG64)mark_sequences(seq, ns, g_mask, base));
        InterlockedExchange64(&g_done, (LONG64)(base + len));
        PostMessageA(g_hwnd, WM_APP, 0, 0);
    }
    free(seq);
    return 0;
}

// Streams the zstd file into a temp file that Windows deletes when the handle closes; returns that handle.
static HANDLE decompress_to_temp(const uint8_t *src, uint64_t n) {
    char dir[MAX_PATH], path[MAX_PATH];
    GetTempPathA(sizeof dir, dir);
    GetTempFileNameA(dir, "vv", 0, path);
    HANDLE t = CreateFileA(path, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_DELETE, NULL, CREATE_ALWAYS,
                           FILE_ATTRIBUTE_TEMPORARY | FILE_FLAG_DELETE_ON_CLOSE, NULL);
    if (t == INVALID_HANDLE_VALUE) return t;
    ZSTD_DCtx *ds = ZSTD_createDStream();
    size_t cap = ZSTD_DStreamOutSize();
    void *buf = malloc(cap);
    ZSTD_inBuffer in = {src, (size_t)n, 0};
    for (;;) {
        ZSTD_outBuffer out = {buf, cap, 0};
        size_t r = ZSTD_decompressStream(ds, &out, &in);
        DWORD w;
        if (ZSTD_isError(r)) { fprintf(stderr, "decompress failed: %s\n", ZSTD_getErrorName(r)); break; }
        if (out.pos && (!WriteFile(t, buf, (DWORD)out.pos, &w, NULL) || w != out.pos)) { fprintf(stderr, "temp write failed\n"); break; }
        if (in.pos == in.size && r == 0) { free(buf); return t; }
        if (in.pos == in.size && out.pos < cap) { fprintf(stderr, "truncated zstd file\n"); break; }
    }
    free(buf);
    CloseHandle(t);
    return INVALID_HANDLE_VALUE;
}

static void human(uint64_t b, char *out, size_t n) {
    const char *u[] = {"B", "KB", "MB", "GB", "TB"};
    double v = (double)b;
    int i = 0;
    while (v >= 1000 && i < 4) { v /= 1000; i++; }
    snprintf(out, n, i ? "%.2f %s" : "%.0f %s", v, u[i]);
}

static int same(View a, View b) { return a.scale == b.scale && a.ox == b.ox && a.oy == b.oy; }

static void hist_push(void) {
    if (g_nback && same(g_back[g_nback - 1], g_v)) return;
    if (g_nback == HIST) memmove(g_back, g_back + 1, sizeof(View) * --g_nback); // drop oldest
    g_back[g_nback++] = g_v;
    g_nfwd = 0;
}

static void hist_push_coalesced(void) { // one entry per burst of wheel/key moves
    DWORD now = GetTickCount();
    if (now - g_lastmove > 500) hist_push();
    g_lastmove = now;
}

static void hist_step(View *from, int *nfrom, View *to, int *nto) {
    if (!*nfrom) return;
    to[(*nto)++] = g_v;
    g_v = from[--*nfrom];
    g_lastmove = 0;
}

static void selftest(void) {
    uint64_t c, s, r;
    assert(parse_dims((const uint8_t *)"01X\nHLX\n", 8, &c, &s, &r) && c == 3 && s == 4 && r == 2);
    assert(parse_dims((const uint8_t *)"01X\nHLX", 7, &c, &s, &r) && c == 3 && s == 4 && r == 2);
    assert(parse_dims((const uint8_t *)"01\r\nHL\r\n", 8, &c, &s, &r) && c == 2 && s == 4 && r == 2);
    assert(!parse_dims((const uint8_t *)"01X\nH\n", 6, &c, &s, &r));
    assert(!parse_dims((const uint8_t *)"\n", 1, &c, &s, &r));
    Instr *in;
    assert(parse_instr("0:44,44:4,48:56", &in) == 3 && in[1].row == 44 && in[1].num == 4 && in[2].num == 56);
    free(in);
    assert(parse_instr("5:1,bad", &in) == 1);
    free(in);
    char b[32];
    human(20072, b, sizeof b); assert(!strcmp(b, "20.07 KB"));
    human(999, b, sizeof b); assert(!strcmp(b, "999 B"));
    View a = {1, 0, 0}, z = {2, 0, 0};
    g_v = a; hist_push(); g_v = z;                                     // navigate a -> z
    hist_step(g_back, &g_nback, g_fwd, &g_nfwd); assert(same(g_v, a) && g_nback == 0 && g_nfwd == 1);
    hist_step(g_back, &g_nback, g_fwd, &g_nfwd); assert(same(g_v, a));  // nothing further back
    hist_step(g_fwd, &g_nfwd, g_back, &g_nback); assert(same(g_v, z) && g_nfwd == 0);
    hist_push(); hist_push(); assert(g_nback == 2);                     // duplicate view not stored twice
    uint8_t m[2] = {0};
    ZSTD_Sequence sq[] = {{1, 2, 3, 0}, {0, 4, 0, 0}}; // LL MMM LLLL from pos 1
    assert(mark_sequences(sq, 2, m, 1) == 6 && m[0] == 0xC6 && m[1] == 0x03); // bits 1,2 and 6..9
    puts("selftest ok");
}

static void fit(void) {
    double gut = g_ninstr ? 1 : 0, sx = g_w / (g_cols + gut), sy = (double)g_gh / g_rows;
    g_v.scale = sx < sy ? sx : sy;
    g_v.ox = -gut;
    g_v.oy = 0;
}

static void zoom_at(double f, int mx, int gy) { // gy: y relative to grid top
    double cx = g_v.ox + mx / g_v.scale, cy = g_v.oy + gy / g_v.scale; // keep the cell under the cursor fixed
    g_v.scale *= f;
    g_v.ox = cx - mx / g_v.scale;
    g_v.oy = cy - gy / g_v.scale;
}

static COLORREF cref(uint32_t c) { return RGB((c >> 16) & 255, (c >> 8) & 255, c & 255); }

static void fill(int x0, int y0, int x1, int y1, uint32_t c) {
    HBRUSH b = CreateSolidBrush(cref(c));
    RECT r = {x0, y0, x1, y1};
    FillRect(g_memdc, &r, b);
    DeleteObject(b);
}

static void draw_instr(void) {
    for (size_t i = 0; i < g_ninstr; i++) {
        double y0 = (g_instr[i].row - g_v.oy) * g_v.scale, x0 = (-1 - g_v.ox) * g_v.scale;
        if (g_instr[i].row >= g_rows || y0 + g_v.scale < 0 || y0 >= g_gh || x0 + g_v.scale < 0 || x0 >= g_w) continue;
        int ix0 = (int)x0, iy0 = HDR + (int)(y0 < 0 ? 0 : y0);
        int ix1 = (int)(x0 + g_v.scale), iy1 = HDR + (int)(y0 + g_v.scale);
        if (ix1 <= ix0) ix1 = ix0 + 1;
        if (iy1 <= iy0) iy1 = iy0 + 1;
        fill(ix0, iy0, ix1, iy1, INSTR);
        char t[24];
        int n = snprintf(t, sizeof t, "%llu", (unsigned long long)g_instr[i].num);
        SIZE sz;
        GetTextExtentPoint32A(g_memdc, t, n, &sz);
        if (sz.cx <= ix1 - ix0 && sz.cy <= iy1 - iy0) { // number only when it fits
            RECT r = {ix0, iy0, ix1, iy1};
            SetTextColor(g_memdc, 0);
            DrawTextA(g_memdc, t, n, &r, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
        }
    }
}

static void draw_header(void) {
    fill(0, 0, g_w, HDR, 0x1E1E1E);
    SetBkMode(g_memdc, TRANSPARENT);
    SetTextColor(g_memdc, RGB(230, 230, 230));
    char t[256], sz[32];
    human(g_size, sz, sizeof sz);
    int n = snprintf(t, sizeof t, "1 B/cell   |   %llu B/vector   |   %llu vectors x %llu pins   |   %s total   |   history  < %d  > %d",
                     (unsigned long long)g_stride, (unsigned long long)g_rows, (unsigned long long)g_cols, sz, g_nback, g_nfwd);
    TextOutA(g_memdc, 8, 4, t, n);
    if (g_csize) {
        char cs[32];
        human(g_csize, cs, sizeof cs);
        uint64_t done = (uint64_t)g_done;
        n = snprintf(t, sizeof t, "zstd file %s (%.2fx)   |   overlay [C] %s: level %d re-run, %.1f%% analysed, literals %.2f%% of analysed bytes   |   cyan = literal, dimmed = match",
                     cs, (double)g_size / g_csize, g_overlay ? "ON" : "off", g_level, 100.0 * done / g_size,
                     done ? 100.0 * g_lits / done : 0.0);
    } else n = snprintf(t, sizeof t, "plain .vec (open a .compr for the compression overlay)");
    TextOutA(g_memdc, 8, 22, t, n);
    static const struct { uint32_t c; const char *s; } leg[] = {
        {0xFFFFFF, "1 drive high"}, {0x000000, "0 drive low"}, {0xFF0000, "H expect high"}, {0x00FF00, "L expect low"},
        {0x800080, "X don't care"}, {INSTR, "instruction"}, {0x808080, "other"}, {LITERAL, "zstd literal (overlay)"}};
    int x = 8;
    for (size_t i = 0; i < sizeof leg / sizeof *leg; i++) {
        fill(x, 43, x + 14, 57, 0x808080); // border so black/white swatches stay visible
        fill(x + 1, 44, x + 13, 56, leg[i].c);
        TextOutA(g_memdc, x + 18, 42, leg[i].s, (int)strlen(leg[i].s));
        SIZE s;
        GetTextExtentPoint32A(g_memdc, leg[i].s, (int)strlen(leg[i].s), &s);
        x += 18 + s.cx + 16;
    }
}

static void render(void) {
    GdiFlush(); // finish pending GDI writes before touching the DIB directly
    uint64_t done = (uint64_t)g_done;
    for (int x = 0; x < g_w; x++) {
        double c = g_v.ox + x / g_v.scale;
        g_colmap[x] = (c >= 0 && c < (double)g_cols) ? (int)c : -1;
    }
    for (int y = 0; y < g_gh; y++) {
        uint32_t *out = g_px + (size_t)(y + HDR) * g_w;
        double r = g_v.oy + y / g_v.scale;
        if (r < 0 || r >= (double)g_rows) { for (int x = 0; x < g_w; x++) out[x] = BG; continue; }
        // shortcut: nearest-cell sampling aliases when zoomed out past 1 cell/pixel, add min/max downsampling if detail gets lost.
        uint64_t off = (uint64_t)r * g_stride;
        const uint8_t *line = g_data + off;
        if (g_overlay && off + g_cols <= done) { // literals flat cyan (black literals must stay visible), matches dimmed
            for (int x = 0; x < g_w; x++)
                out[x] = g_colmap[x] < 0 ? BG : is_literal(off + g_colmap[x]) ? LITERAL
                                                                              : (g_lut[line[g_colmap[x]]] >> 2) & 0x3F3F3F;
        } else
            for (int x = 0; x < g_w; x++) out[x] = g_colmap[x] < 0 ? BG : g_lut[line[g_colmap[x]]];
    }
    draw_instr();
    draw_header();
}

static void resize(HWND hwnd, int w, int h) {
    if (w < 1) w = 1;
    if (h < HDR + 1) h = HDR + 1;
    if (g_bmp) DeleteObject(g_bmp);
    BITMAPINFO bi = {0};
    bi.bmiHeader.biSize = sizeof bi.bmiHeader;
    bi.bmiHeader.biWidth = w;
    bi.bmiHeader.biHeight = -h; // top-down
    bi.bmiHeader.biPlanes = 1;
    bi.bmiHeader.biBitCount = 32;
    bi.bmiHeader.biCompression = BI_RGB;
    HDC dc = GetDC(hwnd);
    g_bmp = CreateDIBSection(dc, &bi, DIB_RGB_COLORS, (void **)&g_px, NULL, 0);
    ReleaseDC(hwnd, dc);
    SelectObject(g_memdc, g_bmp);
    SelectObject(g_memdc, GetStockObject(DEFAULT_GUI_FONT));
    g_colmap = realloc(g_colmap, sizeof(int) * w);
    int first = g_w == 0;
    g_w = w; g_h = h; g_gh = h - HDR;
    if (first) fit();
}

static void update_title(HWND hwnd, int mx, int my) {
    char t[512];
    double c = g_v.ox + mx / g_v.scale, r = g_v.oy + (my - HDR) / g_v.scale;
    int n = snprintf(t, sizeof t, "%s  zoom %.4g", g_name, g_v.scale);
    if (my >= HDR && c >= 0 && c < (double)g_cols && r >= 0 && r < (double)g_rows) {
        uint64_t pos = (uint64_t)r * g_stride + (uint64_t)c;
        n += snprintf(t + n, sizeof t - n, "  | row %llu pin %llu = '%c'", (unsigned long long)r,
                      (unsigned long long)c, g_data[pos]);
        if (g_csize && pos < (uint64_t)g_done) snprintf(t + n, sizeof t - n, "  %s", is_literal(pos) ? "literal" : "match");
    }
    SetWindowTextA(hwnd, t);
}

static LRESULT CALLBACK wndproc(HWND hwnd, UINT m, WPARAM wp, LPARAM lp) {
    switch (m) {
    case WM_SIZE: resize(hwnd, LOWORD(lp), HIWORD(lp)); InvalidateRect(hwnd, NULL, FALSE); return 0;
    case WM_ERASEBKGND: return 1;
    case WM_PAINT: {
        PAINTSTRUCT ps;
        HDC dc = BeginPaint(hwnd, &ps);
        render();
        BitBlt(dc, 0, 0, g_w, g_h, g_memdc, 0, 0, SRCCOPY);
        EndPaint(hwnd, &ps);
        return 0;
    }
    case WM_MOUSEWHEEL: {
        POINT pt = {GET_X_LPARAM(lp), GET_Y_LPARAM(lp)};
        ScreenToClient(hwnd, &pt);
        hist_push_coalesced();
        zoom_at(GET_WHEEL_DELTA_WPARAM(wp) > 0 ? 1.25 : 0.8, pt.x, pt.y - HDR);
        update_title(hwnd, pt.x, pt.y);
        InvalidateRect(hwnd, NULL, FALSE);
        return 0;
    }
    case WM_LBUTTONDOWN:
        hist_push();
        g_drag = 1; g_mx = GET_X_LPARAM(lp); g_my = GET_Y_LPARAM(lp);
        SetCapture(hwnd);
        return 0;
    case WM_LBUTTONUP: g_drag = 0; ReleaseCapture(); return 0;
    case WM_XBUTTONUP:
        if (GET_XBUTTON_WPARAM(wp) == XBUTTON1) hist_step(g_back, &g_nback, g_fwd, &g_nfwd);
        else hist_step(g_fwd, &g_nfwd, g_back, &g_nback);
        InvalidateRect(hwnd, NULL, FALSE);
        return TRUE;
    case WM_MOUSEMOVE: {
        int x = GET_X_LPARAM(lp), y = GET_Y_LPARAM(lp);
        if (g_drag) {
            g_v.ox -= (x - g_mx) / g_v.scale;
            g_v.oy -= (y - g_my) / g_v.scale;
            g_mx = x; g_my = y;
            InvalidateRect(hwnd, NULL, FALSE);
        }
        update_title(hwnd, x, y);
        return 0;
    }
    case WM_KEYDOWN: {
        double step = 0.1 * (wp == VK_LEFT || wp == VK_RIGHT ? g_w : g_gh) / g_v.scale;
        switch (wp) {
        case VK_ESCAPE: DestroyWindow(hwnd); return 0;
        case VK_BACK:
            if (GetKeyState(VK_SHIFT) < 0) hist_step(g_fwd, &g_nfwd, g_back, &g_nback);
            else hist_step(g_back, &g_nback, g_fwd, &g_nfwd);
            break;
        case VK_HOME: case 'F': hist_push(); fit(); break;
        case 'C': g_overlay = g_csize && !g_overlay; break;
        case VK_LEFT: hist_push_coalesced(); g_v.ox -= step; break;
        case VK_RIGHT: hist_push_coalesced(); g_v.ox += step; break;
        case VK_UP: hist_push_coalesced(); g_v.oy -= step; break;
        case VK_DOWN: hist_push_coalesced(); g_v.oy += step; break;
        case VK_OEM_PLUS: case VK_ADD: hist_push_coalesced(); zoom_at(1.25, g_w / 2, g_gh / 2); break;
        case VK_OEM_MINUS: case VK_SUBTRACT: hist_push_coalesced(); zoom_at(0.8, g_w / 2, g_gh / 2); break;
        default: return 0;
        }
        InvalidateRect(hwnd, NULL, FALSE);
        return 0;
    }
    case WM_APP: InvalidateRect(hwnd, NULL, FALSE); return 0; // overlay analysis progressed
    case WM_DESTROY: PostQuitMessage(0); return 0;
    }
    return DefWindowProcA(hwnd, m, wp, lp);
}

int main(int argc, char **argv) {
    if (argc > 1 && !strcmp(argv[1], "--selftest")) { selftest(); return 0; }
    if (argc < 2) { fprintf(stderr, "usage: vecview <Vectors.vec | vector_N.compr> [row:num,...] | --selftest\n"); return 2; }
    const char *base = strrchr(argv[1], '\\'), *slash = strrchr(argv[1], '/');
    if (!base || (slash && slash > base)) base = slash;
    snprintf(g_name, sizeof g_name, "%s", base ? base + 1 : argv[1]);

    HANDLE f = CreateFileA(argv[1], GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_FLAG_RANDOM_ACCESS, NULL);
    if (f == INVALID_HANDLE_VALUE) { fprintf(stderr, "cannot open %s\n", argv[1]); return 1; }
    LARGE_INTEGER sz;
    GetFileSizeEx(f, &sz);
    g_size = (uint64_t)sz.QuadPart;
    HANDLE map = g_size ? CreateFileMappingA(f, NULL, PAGE_READONLY, 0, 0, NULL) : NULL;
    g_data = map ? MapViewOfFile(map, FILE_MAP_READ, 0, 0, 0) : NULL;
    if (!g_data) { fprintf(stderr, "cannot map %s (empty file or out of address space)\n", argv[1]); return 1; }

    if (g_size >= 4 && !memcmp(g_data, "\x28\xB5\x2F\xFD", 4)) { // zstd frame magic
        g_csize = g_size;
        HANDLE t = decompress_to_temp(g_data, g_size);
        if (t == INVALID_HANDLE_VALUE) { fprintf(stderr, "cannot decompress %s\n", argv[1]); return 1; }
        UnmapViewOfFile(g_data);
        CloseHandle(map);
        CloseHandle(f);
        GetFileSizeEx(t, &sz);
        g_size = (uint64_t)sz.QuadPart;
        map = g_size ? CreateFileMappingA(t, NULL, PAGE_READONLY, 0, 0, NULL) : NULL;
        g_data = map ? MapViewOfFile(map, FILE_MAP_READ, 0, 0, 0) : NULL;
        if (!g_data) { fprintf(stderr, "%s: empty or unmappable after decompression\n", argv[1]); return 1; }
        const char *u = strrchr(g_name, '_'); // level from vector_<level>.compr, else zstd default 3
        g_level = u ? atoi(u + 1) : 3;
        if (!g_level) g_level = 3;
        // shortcut: mask is 1 bit/byte in RAM (125 MB per GB), map it from a temp file too if RAM becomes the limit.
        g_mask = calloc(g_size / 8 + 1, 1);
        if (!g_mask) { fprintf(stderr, "out of memory for overlay mask\n"); return 1; }
        g_overlay = 1;
    }
    if (!parse_dims(g_data, g_size, &g_cols, &g_stride, &g_rows)) {
        fprintf(stderr, "%s: lines are not all the same width\n", argv[1]);
        return 1;
    }
    if (argc > 2) g_ninstr = parse_instr(argv[2], &g_instr);

    for (int i = 0; i < 256; i++) g_lut[i] = 0x808080; // unknown chars: gray
    g_lut['1'] = 0xFFFFFF; g_lut['0'] = 0x000000;
    g_lut['H'] = 0xFF0000; g_lut['L'] = 0x00FF00; g_lut['X'] = 0x800080;

    HINSTANCE inst = GetModuleHandleA(NULL);
    WNDCLASSA wc = {0};
    wc.lpfnWndProc = wndproc;
    wc.hInstance = inst;
    wc.hCursor = LoadCursor(NULL, IDC_CROSS);
    wc.lpszClassName = "vecview";
    RegisterClassA(&wc);
    g_memdc = CreateCompatibleDC(NULL);
    HWND hwnd = CreateWindowA("vecview", g_name, WS_OVERLAPPEDWINDOW | WS_VISIBLE,
                              CW_USEDEFAULT, CW_USEDEFAULT, 1280, 800, NULL, NULL, inst, NULL);
    update_title(hwnd, -1, -1);
    g_hwnd = hwnd;
    if (g_csize) CloseHandle(CreateThread(NULL, 0, analyse, NULL, 0, NULL));

    MSG msg;
    while (GetMessageA(&msg, NULL, 0, 0) > 0) { TranslateMessage(&msg); DispatchMessageA(&msg); }
    return 0;
}
