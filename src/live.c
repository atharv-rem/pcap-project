/* live.c - [M3] raylib window that replays ONE storm from the real model, step by step.
 *
 * usage: build/live --grid data_ds3/grid.bin --meta data_ds3/grid.meta --intensity 40
 *                   --duration 2.5 [--threshold 0.3] [--steps-per-frame 2]
 *                   [--spots data/known_spots.csv] [--places data/places.csv]
 *                   [--font /path/to/font.ttf] [--basemap data/raw/osm/basemap_muted.png]
 *
 * Single process, no MPI. Uses only grid_load, sim_begin, sim_step, sim_depth, sim_time_s
 * and sim_raining from sim.h. The grid is one texture, rewritten every frame: grey
 * hillshade, water on top from light to dark blue (full dark at WATER_FULL_M), cells deeper
 * than the threshold drawn stronger. Keys: SPACE pause, UP/DOWN steps per frame, R restart,
 * ESC quit; mouse wheel zooms, dragging moves the map, F fits it again, and the cell under
 * the mouse is described (lat/lon, ground height, water depth); H hides the help, P the
 * place names (data/places.csv: map labels only, not used for validation). Text uses
 * a plain system sans-serif (DejaVu Sans) when available. If the OpenStreetMap basemap made
 * by scripts/osm_basemap.py exists, the water is drawn over the street map instead of the
 * terrain shading; B switches between the two. Only a few steps run per frame,
 * so the window stays responsive.
 */
#define _POSIX_C_SOURCE 200809L
#include "sim.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <raylib.h>

#define WIN_W         900
#define WIN_H         900
#define WATER_MIN_M   0.005f   /* shallower water is not drawn */
#define WATER_FULL_M  2.0f     /* full dark blue at this depth */
#define SPF_MIN       1
#define SPF_MAX       50
#define MAX_SPOTS     512
#define MAX_LABELLED  20       /* more flood spots than this: dots only, name on hover */
#define ZOOM_MAX      40.0f    /* at most 40x the fitted size */
#define TARGET_FPS    30       /* 2.5 h storm = 540 steps: ~9 s at 2 steps/frame, ~18 s at 1 */

typedef struct {
    const char *grid, *meta, *spots, *places, *basemap, *font;
    float intensity, duration, threshold;
    int spf;
} Args;

typedef struct {
    double lat_top, lon_left, cell_deg;
    int ok;
} GeoMeta;

typedef struct {
    char name[128];
    float row, col;            /* fractional cell position */
} Spot;

static void usage(void)
{
    fprintf(stderr,
            "usage: live --grid data_ds3/grid.bin --meta data_ds3/grid.meta\n"
            "            --intensity 40 --duration 2.5 [--threshold 0.3]\n"
            "            [--steps-per-frame 2] [--spots data/known_spots.csv]\n"
            "            [--places data/places.csv] [--font /path/to/font.ttf]\n"
            "            [--basemap data/raw/osm/basemap_muted.png | none]\n");
}

static int parse_args(int argc, char **argv, Args *a)
{
    *a = (Args){"data_ds3/grid.bin", "data_ds3/grid.meta", "data/known_spots.csv",
                "data/places.csv", "data/raw/osm/basemap_muted.png", NULL,
                40.0f, 2.5f, 0.3f, 2};
    for (int i = 1; i < argc; i++) {
        const char *k = argv[i];
        if (i + 1 >= argc) {
            fprintf(stderr, "missing value for %s\n", k);
            return -1;
        }
        const char *v = argv[++i];
        if (!strcmp(k, "--grid")) a->grid = v;
        else if (!strcmp(k, "--meta")) a->meta = v;
        else if (!strcmp(k, "--spots")) a->spots = v;
        else if (!strcmp(k, "--font")) a->font = v;
        else if (!strcmp(k, "--places")) a->places = v;
        else if (!strcmp(k, "--basemap")) a->basemap = v;
        else if (!strcmp(k, "--intensity")) a->intensity = (float)atof(v);
        else if (!strcmp(k, "--duration")) a->duration = (float)atof(v);
        else if (!strcmp(k, "--threshold")) a->threshold = (float)atof(v);
        else if (!strcmp(k, "--steps-per-frame")) a->spf = atoi(v);
        else {
            fprintf(stderr, "unknown option %s\n", k);
            return -1;
        }
    }
    if (a->intensity <= 0.0f || a->duration <= 0.0f || a->threshold <= 0.0f) {
        fprintf(stderr, "--intensity, --duration and --threshold must be > 0\n");
        return -1;
    }
    if (a->spf < SPF_MIN) a->spf = SPF_MIN;
    if (a->spf > SPF_MAX) a->spf = SPF_MAX;
    return 0;
}

/* lat_top, lon_left, cell_deg from the meta file (grid_load reads only the size). */
static GeoMeta read_geo(const char *meta_path)
{
    GeoMeta m = {0, 0, 0, 0};
    FILE *f = fopen(meta_path, "r");
    if (!f)
        return m;
    char line[256];
    int got = 0;
    while (fgets(line, sizeof line, f)) {
        char key[64], val[128];
        if (sscanf(line, " %63[^= ] = %127s", key, val) != 2)
            continue;
        if (!strcmp(key, "lat_top")) { m.lat_top = atof(val); got |= 1; }
        else if (!strcmp(key, "lon_left")) { m.lon_left = atof(val); got |= 2; }
        else if (!strcmp(key, "cell_deg")) { m.cell_deg = atof(val); got |= 4; }
    }
    fclose(f);
    m.ok = got == 7 && m.cell_deg > 0.0;
    return m;
}

/* name,lat,lon rows (known spots, contract C5, or place names) inside the grid.
   Rows without coordinates or outside the grid are skipped. */
static int load_spots(const char *path, const GeoMeta *m, const Grid *g, Spot *out)
{
    FILE *f = fopen(path, "r");
    if (!f || !m->ok) {
        if (f)
            fclose(f);
        return 0;
    }
    char line[1024];
    int n = 0, first = 1;
    while (fgets(line, sizeof line, f) && n < MAX_SPOTS) {
        if (first) { first = 0; continue; }          /* header */
        char *name = strtok(line, ",\r\n");
        char *lat_s = strtok(NULL, ",\r\n");
        char *lon_s = strtok(NULL, ",\r\n");
        if (!name || !lat_s || !lon_s) {
            if (name)
                printf("live: %s: skipped '%s': blank lat or lon\n", path, name);
            continue;
        }
        double lat = atof(lat_s), lon = atof(lon_s);
        if (!isfinite(lat) || !isfinite(lon)) {
            printf("live: %s: skipped '%s': lat/lon not numbers\n", path, name);
            continue;
        }
        float r = (float)((m->lat_top - lat) / m->cell_deg);
        float c = (float)((lon - m->lon_left) / m->cell_deg);
        if (r < 0 || c < 0 || r >= g->rows || c >= g->cols) {
            printf("live: %s: skipped '%s': outside the grid\n", path, name);
            continue;
        }
        snprintf(out[n].name, sizeof out[n].name, "%s", name);
        out[n].row = r;
        out[n].col = c;
        n++;
    }
    fclose(f);
    return n;
}

/* Grey hillshade, 0..255 per cell, light from the north-west at 45 degrees. */
static unsigned char *make_hillshade(const Grid *g)
{
    const int rows = g->rows, cols = g->cols;
    unsigned char *shade = malloc((size_t)rows * cols);
    if (!shade)
        return NULL;
    const float vexag = 4.0f, d = g->cell_size_m;
    const float az = 315.0f * 3.14159265f / 180.0f, alt = 45.0f * 3.14159265f / 180.0f;
    const float lx = sinf(az) * cosf(alt), ly = cosf(az) * cosf(alt), lz = sinf(alt);
    for (int r = 0; r < rows; r++) {
        for (int c = 0; c < cols; c++) {
            const float *z = g->height;
            int c0 = c > 0 ? c - 1 : c, c1 = c < cols - 1 ? c + 1 : c;
            int r0 = r > 0 ? r - 1 : r, r1 = r < rows - 1 ? r + 1 : r;
            float dzdx = (z[(size_t)r * cols + c1] - z[(size_t)r * cols + c0]) / ((c1 - c0) * d);
            float dzdy = (z[(size_t)r0 * cols + c] - z[(size_t)r1 * cols + c]) / ((r1 - r0) * d);
            float nx = -dzdx * vexag, ny = -dzdy * vexag, nz = 1.0f;
            float len = sqrtf(nx * nx + ny * ny + nz * nz);
            float s = (nx * lx + ny * ly + nz * lz) / len;
            if (s < 0.0f) s = 0.0f;
            float grey = 0.55f + 0.45f * s;         /* soft, like the risk map */
            shade[(size_t)r * cols + c] = (unsigned char)(grey * 255.0f);
        }
    }
    return shade;
}

/* Paint terrain + water into the RGBA buffer; returns the number of flooded cells.
   shade == NULL: water only, dry cells transparent (drawn over the street map). */
static int paint(const float *depth, const unsigned char *shade, size_t n, float threshold,
                 unsigned char *rgba)
{
    /* light blue (183,211,246) -> dark blue (13,54,107) */
    const float lo[3] = {183, 211, 246}, hi[3] = {13, 54, 107};
    int flooded = 0;
    for (size_t i = 0; i < n; i++) {
        float d = depth[i];
        if (!shade) {
            unsigned char *px = &rgba[4 * i];
            if (d <= WATER_MIN_M) {
                px[0] = px[1] = px[2] = px[3] = 0;
                continue;
            }
            float t = fminf(d / WATER_FULL_M, 1.0f), a;
            if (d > threshold) {
                flooded++;
                t = fmaxf(t, 0.3f);
                a = 0.92f;
            } else {
                a = 0.30f + 0.45f * d / threshold;
            }
            for (int k = 0; k < 3; k++)
                px[k] = (unsigned char)(lo[k] + (hi[k] - lo[k]) * t);
            px[3] = (unsigned char)(a * 255.0f);
            continue;
        }
        float out[3] = {shade[i], shade[i], shade[i]};
        if (d > WATER_MIN_M) {
            float t = d / WATER_FULL_M;
            if (t > 1.0f) t = 1.0f;
            float a;
            if (d > threshold) {                    /* flooded: stronger */
                flooded++;
                if (t < 0.3f) t = 0.3f;
                a = 0.95f;
            } else {
                a = 0.25f + 0.45f * d / threshold;
            }
            for (int k = 0; k < 3; k++) {
                float w = lo[k] + (hi[k] - lo[k]) * t;
                out[k] = out[k] * (1.0f - a) + w * a;
            }
        }
        rgba[4 * i + 0] = (unsigned char)out[0];
        rgba[4 * i + 1] = (unsigned char)out[1];
        rgba[4 * i + 2] = (unsigned char)out[2];
        rgba[4 * i + 3] = 255;
    }
    return flooded;
}

/* Screen pixels per cell and the screen position of the grid's top-left corner. */
typedef struct {
    float scale, ox, oy;
} View;

/* The whole grid fitted into the window, square cells, centred. */
static View view_fit(const Grid *g)
{
    const int sw = GetScreenWidth(), sh = GetScreenHeight();
    View v;
    v.scale = fminf((float)sw / g->cols, (float)sh / g->rows);
    v.ox = (sw - g->cols * v.scale) / 2;
    v.oy = (sh - g->rows * v.scale) / 2;
    return v;
}

/* Mouse wheel zooms around the cursor, dragging (left or right button) moves the map,
   F fits it again. The window centre always stays on the map, so it cannot get lost. */
static void view_update(View *v, const View *fit, const Grid *g)
{
    const Vector2 m = GetMousePosition();
    const float wheel = GetMouseWheelMove();
    if (wheel != 0.0f) {
        float ns = v->scale * powf(1.25f, wheel);
        if (ns < fit->scale) ns = fit->scale;
        if (ns > fit->scale * ZOOM_MAX) ns = fit->scale * ZOOM_MAX;
        v->ox = m.x - (m.x - v->ox) * ns / v->scale;   /* keep the cell under the cursor */
        v->oy = m.y - (m.y - v->oy) * ns / v->scale;
        v->scale = ns;
    }
    if (IsMouseButtonDown(MOUSE_BUTTON_LEFT) || IsMouseButtonDown(MOUSE_BUTTON_RIGHT)) {
        const Vector2 d = GetMouseDelta();
        v->ox += d.x;
        v->oy += d.y;
    }
    if (IsKeyPressed(KEY_F))
        *v = *fit;
    const float cx = GetScreenWidth() / 2.0f, cy = GetScreenHeight() / 2.0f;
    v->ox = fminf(fmaxf(v->ox, cx - g->cols * v->scale), cx);
    v->oy = fminf(fmaxf(v->oy, cy - g->rows * v->scale), cy);
}

/* ---- user interface: fonts, colours, panels ---- */

#define FONT_LOAD_PX  48       /* glyphs are rasterised once at this size, then scaled */
#define POST_RAIN_S   7200.0   /* contract C2: 240 drain steps of 30 s after the rain */

static const Color UI_PANEL = {18, 20, 24, 225};
static const Color UI_TEXT  = {240, 239, 236, 255};
static const Color UI_MUTED = {160, 164, 170, 255};
static const Color UI_TRACK = {62, 66, 72, 255};
static const Color UI_BLUE  = {57, 135, 229, 255};
static const Color UI_AMBER = {222, 150, 30, 255};
static const Color UI_GREEN = {27, 175, 122, 255};
static const Color UI_GREY  = {120, 124, 130, 255};
static const Color SWATCH_SHALLOW = {150, 185, 230, 255};
static const Color SWATCH_FLOOD   = {20, 62, 130, 255};

static Font ui_font, ui_bold;

/* Plain sans-serif system fonts, first one found wins; raylib's own font if none is. */
static const char *FONT_REGULAR[] = {
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
};
static const char *FONT_BOLD[] = {
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
};

static Font load_ttf(const char *path)
{
    int cps[95 + 4], n = 0;          /* printable ASCII plus degree, squared, dot, (c) */
    for (int c = 32; c < 127; c++)
        cps[n++] = c;
    cps[n++] = 0xB0;
    cps[n++] = 0xB2;
    cps[n++] = 0xB7;
    cps[n++] = 0xA9;
    Font f = LoadFontEx(path, FONT_LOAD_PX, cps, n);
    SetTextureFilter(f.texture, TEXTURE_FILTER_BILINEAR);
    return f;
}

static void load_fonts(const char *user_font)
{
    ui_font = ui_bold = GetFontDefault();
    if (user_font && FileExists(user_font)) {
        ui_font = ui_bold = load_ttf(user_font);
        return;
    }
    for (size_t k = 0; k < sizeof FONT_REGULAR / sizeof *FONT_REGULAR; k++) {
        if (FileExists(FONT_REGULAR[k])) {
            ui_font = load_ttf(FONT_REGULAR[k]);
            ui_bold = FileExists(FONT_BOLD[k]) ? load_ttf(FONT_BOLD[k]) : ui_font;
            return;
        }
    }
    printf("live: no TTF font found, using raylib's built-in font\n");
}

static void unload_fonts(void)
{
    const unsigned int def = GetFontDefault().texture.id;
    if (ui_bold.texture.id != def && ui_bold.texture.id != ui_font.texture.id)
        UnloadFont(ui_bold);
    if (ui_font.texture.id != def)
        UnloadFont(ui_font);
}

static void text(const char *s, float x, float y, float size, Color c)
{
    DrawTextEx(ui_font, s, (Vector2){x, y}, size, 0.0f, c);
}

static void text_bold(const char *s, float x, float y, float size, Color c)
{
    DrawTextEx(ui_bold, s, (Vector2){x, y}, size, 0.0f, c);
}

static float text_width(Font f, const char *s, float size)
{
    return MeasureTextEx(f, s, size, 0.0f).x;
}

static void rounded(float x, float y, float w, float h, float radius, Color c)
{
    float m = fminf(w, h);
    DrawRectangleRounded((Rectangle){x, y, w, h}, m > 0 ? fminf(1.0f, 2 * radius / m) : 0, 8, c);
}

/* A small coloured label with white bold text; returns its width. */
static float pill(const char *s, float x, float y, Color bg)
{
    float w = text_width(ui_bold, s, 13) + 16;
    rounded(x, y, w, 22, 11, bg);
    text_bold(s, x + 8, y + 4, 13, WHITE);
    return w;
}

/* 12345 -> "12,345" */
static const char *thousands(int v)
{
    static char out[32];
    char raw[24];
    snprintf(raw, sizeof raw, "%d", v);
    int len = (int)strlen(raw), j = 0;
    for (int i = 0; i < len; i++) {
        out[j++] = raw[i];
        if (raw[i] != '-' && (len - i - 1) % 3 == 0 && i < len - 1)
            out[j++] = ',';
    }
    out[j] = '\0';
    return out;
}

/* seconds -> "2h 05m" (each call has its own buffer, so two can share one TextFormat) */
static const char *hm(double secs, char *buf, size_t size)
{
    int total = (int)(secs / 60 + 0.5);
    snprintf(buf, size, "%dh %02dm", total / 60, total % 60);
    return buf;
}

typedef struct {
    Scenario sc;
    double t_s, rain_end_s, end_s;
    int running, paused, raining, flooded, spf;
    float threshold, cell_km2, zoom;
} Status;

/* Top-left card: storm, clock, phase, progress through rain and drain, flooded area. */
static void draw_status(const Status *st)
{
    const float x = 16, y = 16, w = 344, h = 236, px = x + 18;
    char b1[16], b2[16];
    rounded(x, y, w, h, 12, UI_PANEL);
    text_bold("Bengaluru flood model", px, y + 16, 20, UI_TEXT);
    text(TextFormat("Storm: %g mm/h of rain for %s", st->sc.intensity_mm_hr,
                    hm(st->sc.duration_hr * 3600.0, b1, sizeof b1)), px, y + 44, 15, UI_MUTED);

    const char *clock = hm(st->t_s, b1, sizeof b1);
    text_bold(clock, px, y + 70, 32, UI_TEXT);
    const char *label;
    Color c;
    if (!st->running)      { label = "FINISHED"; c = UI_GREEN; }
    else if (st->paused)   { label = "PAUSED";   c = UI_GREY; }
    else if (st->raining)  { label = "RAINING";  c = UI_BLUE; }
    else                   { label = "DRAINING"; c = UI_AMBER; }
    pill(label, px + text_width(ui_bold, clock, 32) + 14, y + 79, c);

    /* progress bar: blue while it rains, amber while it drains */
    const float bx = px, by = y + 118, bw = w - 36, bh = 8;
    const float split = (float)(st->rain_end_s / st->end_s) * bw;
    const float done = (float)fmin(st->t_s / st->end_s, 1.0) * bw;
    rounded(bx, by, bw, bh, 4, UI_TRACK);
    if (done > 0)
        rounded(bx, by, fminf(done, split), bh, 4, UI_BLUE);
    if (done > split)
        rounded(bx + split, by, done - split, bh, 4, UI_AMBER);
    DrawRectangle((int)(bx + split) - 1, (int)by - 3, 2, (int)bh + 6, UI_TEXT);
    text(TextFormat("rain %s", hm(st->rain_end_s, b1, sizeof b1)), bx, by + 14, 13, UI_MUTED);
    const char *drain = TextFormat("then drain %s",
                                   hm(st->end_s - st->rain_end_s, b2, sizeof b2));
    text(drain, bx + bw - text_width(ui_font, drain, 13), by + 14, 13, UI_MUTED);

    text(TextFormat("Flooded now (water deeper than %.2g m)", st->threshold),
         px, y + 160, 14, UI_MUTED);
    char cells[48];
    snprintf(cells, sizeof cells, "%s cells", thousands(st->flooded));
    text_bold(cells, px, y + 180, 22, UI_TEXT);
    text(TextFormat("= %.1f km\xc2\xb2", st->flooded * st->cell_km2),
         px + text_width(ui_bold, cells, 22) + 8, y + 184, 17, UI_MUTED);

    text(TextFormat("speed %d steps/frame  \xc2\xb7  %d fps  \xc2\xb7  zoom %.1fx",
                    st->spf, GetFPS(), st->zoom), px, y + 212, 13, UI_MUTED);
}

/* Top-right card: the controls, hidden with H. */
static void draw_help(int sw, int show)
{
    static const char *keys[][2] = {
        {"Space", "pause / resume"}, {"Up / Down", "faster / slower"},
        {"R", "restart the storm"}, {"Mouse wheel", "zoom in / out"},
        {"Drag", "move the map"}, {"F", "show the whole map"},
        {"B", "street map / terrain"}, {"P", "show / hide place names"},
        {"H", "hide this help"}, {"Esc", "quit"},
    };
    const int n = (int)(sizeof keys / sizeof *keys);
    if (!show) {
        const char *s = "H  help";
        float w = text_width(ui_font, s, 14) + 24;
        rounded(sw - 16 - w, 16, w, 30, 10, UI_PANEL);
        text(s, sw - 16 - w + 12, 23, 14, UI_TEXT);
        return;
    }
    const float w = 290, x = sw - 16 - w, y = 16;
    rounded(x, y, w, 46 + n * 22.0f, 12, UI_PANEL);
    text_bold("Controls", x + 16, y + 14, 16, UI_TEXT);
    for (int k = 0; k < n; k++) {
        text_bold(keys[k][0], x + 16, y + 42 + k * 22.0f, 14, UI_TEXT);
        text(keys[k][1], x + 112, y + 42 + k * 22.0f, 14, UI_MUTED);
    }
}

/* Bottom-right card: what the colours mean. */
static void draw_legend(int sw, int sh, float threshold, int n_spots, int street_map)
{
    const float w = 240, h = 160, x = sw - 16 - w, y = sh - 16 - h;
    rounded(x, y, w, h, 12, UI_PANEL);
    text_bold("Legend", x + 16, y + 12, 16, UI_TEXT);
    rounded(x + 16, y + 40, 16, 16, 4, SWATCH_SHALLOW);
    text("shallow water", x + 42, y + 40, 14, UI_TEXT);
    rounded(x + 16, y + 64, 16, 16, 4, SWATCH_FLOOD);
    text(TextFormat("flooded (over %.2g m)", threshold), x + 42, y + 64, 14, UI_TEXT);
    if (n_spots > MAX_LABELLED) {
        DrawCircle((int)x + 24, (int)y + 96, 3.5f, WHITE);
        DrawCircle((int)x + 24, (int)y + 96, 2.2f, (Color){200, 40, 40, 255});
        text(TextFormat("known flood point (%d)", n_spots), x + 42, y + 88, 14, UI_TEXT);
    } else {
        DrawCircle((int)x + 24, (int)y + 96, 6, WHITE);
        DrawCircleLines((int)x + 24, (int)y + 96, 6, BLACK);
        text("known flood spot", x + 42, y + 88, 14, UI_TEXT);
    }
    DrawCircle((int)x + 24, (int)y + 120, 3.5f, UI_TEXT);
    text("place name (P on / off)", x + 42, y + 112, 14, UI_TEXT);
    text(street_map ? "map \xc2\xa9 OpenStreetMap contributors"
                    : "grey shading = hills and valleys", x + 16, y + 136, 12, UI_MUTED);
}

/* Bottom-left card: the cell under the mouse. */
static void draw_probe(int sh, const Grid *g, const GeoMeta *geo, const Spot *spots,
                       int n_spots, const Spot *places, int n_places, int r, int c,
                       float depth, float threshold)
{
    const float w = 400, h = 102, x = 16, y = sh - 16 - h, px = x + 16;
    rounded(x, y, w, h, 12, UI_PANEL);
    if (geo->ok)
        text_bold(TextFormat("Latitude %.4f\xc2\xb0   Longitude %.4f\xc2\xb0",
                             geo->lat_top - (r + 0.5) * geo->cell_deg,
                             geo->lon_left + (c + 0.5) * geo->cell_deg),
                  px, y + 12, 16, UI_TEXT);
    else
        text_bold(TextFormat("row %d, column %d", r, c), px, y + 12, 16, UI_TEXT);
    text(TextFormat("ground %.0f m above sea level", g->height[(size_t)r * g->cols + c]),
         px, y + 36, 14, UI_MUTED);

    char wl[48];
    if (depth > WATER_MIN_M)
        snprintf(wl, sizeof wl, "water %.2f m deep", depth);
    else
        snprintf(wl, sizeof wl, "dry");
    text(wl, px, y + 58, 15, UI_TEXT);
    if (depth > threshold)
        pill("FLOODED", px + text_width(ui_font, wl, 15) + 10, y + 55, SWATCH_FLOOD);

    /* nearest known spot or place within 1 km */
    const Spot *best = NULL;
    float best_m = 1000.0f;
    for (int k = 0; k < n_spots + n_places; k++) {
        const Spot *p = k < n_spots ? &spots[k] : &places[k - n_spots];
        float dm = hypotf(p->row - (r + 0.5f), p->col - (c + 0.5f)) * g->cell_size_m;
        if (dm <= best_m) {
            best_m = dm;
            best = p;
        }
    }
    if (best) {
        char near[72];
        snprintf(near, sizeof near, "%.0f m from %.52s%s", best_m, best->name,
                 strlen(best->name) > 52 ? "..." : "");
        text(near, px, y + 80, 13, UI_MUTED);
    }
}

static Rectangle spot_label_box(const Spot *p, const View *v)
{
    float x = v->ox + p->col * v->scale, y = v->oy + p->row * v->scale;
    return (Rectangle){x - 7, y - 11, text_width(ui_bold, p->name, 13) + 30, 22};
}

/* Flood spots always get a dark label; a place name is drawn (light label) only where it
   does not overlap a label already placed, so zooming in reveals more of them. */
static void draw_labels(const Spot *spots, int n_spots, const Spot *places, int n_places,
                        int show_places, const View *v, const Rectangle *cards, int n_cards)
{
    static Rectangle taken[2 * MAX_SPOTS + 8];
    int nt = 0;
    const int label_spots = n_spots <= MAX_LABELLED;
    for (int k = 0; k < n_cards; k++)          /* no place name hidden under a card */
        taken[nt++] = cards[k];
    for (int k = 0; label_spots && k < n_spots; k++)
        taken[nt++] = spot_label_box(&spots[k], v);

    for (int k = 0; show_places && k < n_places; k++) {
        float x = v->ox + places[k].col * v->scale, y = v->oy + places[k].row * v->scale;
        float tw = text_width(ui_bold, places[k].name, 12);
        Rectangle box = {x - 4, y - 10, tw + 22, 20};
        int clash = 0;
        for (int j = 0; j < nt && !clash; j++)
            clash = CheckCollisionRecs(box, taken[j]);
        if (clash)
            continue;
        taken[nt++] = box;
        rounded(x + 7, y - 10, tw + 12, 20, 7, (Color){255, 255, 255, 205});
        text_bold(places[k].name, x + 13, y - 6, 12, (Color){40, 42, 46, 255});
        DrawCircle((int)x, (int)y, 3.5f, (Color){40, 42, 46, 255});
    }

    for (int k = 0; !label_spots && k < n_spots; k++) {
        float x = v->ox + spots[k].col * v->scale, y = v->oy + spots[k].row * v->scale;
        DrawCircle((int)x, (int)y, 3.5f, WHITE);
        DrawCircle((int)x, (int)y, 2.2f, (Color){200, 40, 40, 255});
    }
    for (int k = 0; label_spots && k < n_spots; k++) {
        float x = v->ox + spots[k].col * v->scale, y = v->oy + spots[k].row * v->scale;
        float tw = text_width(ui_bold, spots[k].name, 13);
        rounded(x + 10, y - 11, tw + 12, 22, 8, (Color){18, 20, 24, 215});
        text_bold(spots[k].name, x + 16, y - 7, 13, UI_TEXT);
        DrawCircle((int)x, (int)y, 6, WHITE);
        DrawCircleLines((int)x, (int)y, 6, BLACK);
    }
}

int main(int argc, char **argv)
{
    Args a;
    if (parse_args(argc, argv, &a) != 0) {
        usage();
        return 2;
    }
    Grid g;
    if (grid_load(a.grid, a.meta, &g) != 0)
        return 1;
    const size_t n = (size_t)g.rows * g.cols;
    SimState *s = sim_create(&g);
    unsigned char *shade = make_hillshade(&g);
    unsigned char *rgba = malloc(n * 4);
    if (!s || !shade || !rgba) {
        fprintf(stderr, "live: out of memory\n");
        return 1;
    }
    GeoMeta geo = read_geo(a.meta);
    Spot spots[MAX_SPOTS];
    int n_spots = load_spots(a.spots, &geo, &g, spots);
    static Spot places[MAX_SPOTS];
    int n_places = load_spots(a.places, &geo, &g, places);

    const Scenario sc = {a.intensity, a.duration};
    sim_begin(s, sc);
    printf("live: grid %dx%d (%.0f m), storm %.1f mm/h x %.2f h, threshold %.2f m, "
           "%d known spots, %d place names\n", g.rows, g.cols, g.cell_size_m,
           sc.intensity_mm_hr, sc.duration_hr, a.threshold, n_spots, n_places);

    SetConfigFlags(FLAG_WINDOW_RESIZABLE | FLAG_MSAA_4X_HINT);
    SetTraceLogLevel(LOG_WARNING);
    InitWindow(WIN_W, WIN_H, "Bengaluru flood model - live storm");
    if (!IsWindowReady()) {
        fprintf(stderr, "live: could not open a window (is a display available? "
                        "In WSL this needs WSLg)\n");
        return 1;
    }
    SetTargetFPS(TARGET_FPS);
    SetExitKey(KEY_ESCAPE);
    load_fonts(a.font);

    Image img = GenImageColor(g.cols, g.rows, BLACK);
    Texture2D tex = LoadTextureFromImage(img);
    UnloadImage(img);
    SetTextureFilter(tex, TEXTURE_FILTER_POINT);

    /* optional OpenStreetMap basemap: it covers exactly the grid area (osm_basemap.py) */
    Texture2D base = {0};
    if (strcmp(a.basemap, "none") != 0 && FileExists(a.basemap)) {
        base = LoadTexture(a.basemap);
        float grid_aspect = (float)g.cols / g.rows;
        if (base.id && fabsf((float)base.width / base.height - grid_aspect) > 0.02f * grid_aspect) {
            printf("live: %s has a different shape than the grid, not used\n", a.basemap);
            UnloadTexture(base);
            base.id = 0;
        }
        if (base.id)
            SetTextureFilter(base, TEXTURE_FILTER_BILINEAR);
    }
    if (!base.id)
        printf("live: no street map (run scripts/osm_basemap.py), showing the terrain\n");

    /* the storm's own clock: rain (whole 30 s steps) then the fixed drain window */
    const double rain_end = ceil(sc.duration_hr * 3600.0 / 30.0) * 30.0;
    int paused = 0, running = 1, spf = a.spf, show_help = 1;
    int show_base = base.id != 0;
    int show_places = !show_base;     /* the street map already names the places */
    int last_w = GetScreenWidth(), last_h = GetScreenHeight();
    View view = view_fit(&g);
    while (!WindowShouldClose()) {
        if (IsKeyPressed(KEY_SPACE)) paused = !paused;
        if (IsKeyPressed(KEY_UP) && spf < SPF_MAX) spf++;
        if (IsKeyPressed(KEY_DOWN) && spf > SPF_MIN) spf--;
        if (IsKeyPressed(KEY_H)) show_help = !show_help;
        if (IsKeyPressed(KEY_P)) show_places = !show_places;
        if (IsKeyPressed(KEY_B) && base.id) show_base = !show_base;
        if (IsKeyPressed(KEY_R)) {
            sim_begin(s, sc);
            running = 1;
            paused = 0;
        }
        if (running && !paused)
            running = sim_step(s, spf);

        int flooded = paint(sim_depth(s), show_base ? NULL : shade, n, a.threshold, rgba);
        UpdateTexture(tex, rgba);

        const int sw = GetScreenWidth(), sh = GetScreenHeight();
        View fit = view_fit(&g);
        if (sw != last_w || sh != last_h) {         /* window resized: fit again */
            view = fit;
            last_w = sw;
            last_h = sh;
        }
        view_update(&view, &fit, &g);

        BeginDrawing();
        ClearBackground((Color){14, 15, 18, 255});
        if (show_base)
            DrawTexturePro(base, (Rectangle){0, 0, (float)base.width, (float)base.height},
                           (Rectangle){view.ox, view.oy, g.cols * view.scale,
                                       g.rows * view.scale}, (Vector2){0, 0}, 0.0f, WHITE);
        DrawTexturePro(tex, (Rectangle){0, 0, (float)g.cols, (float)g.rows},
                       (Rectangle){view.ox, view.oy, g.cols * view.scale, g.rows * view.scale},
                       (Vector2){0, 0}, 0.0f, WHITE);
        /* screen areas of the cards drawn below (status, controls, legend, probe) */
        const Rectangle cards[] = {
            {16, 16, 344, 236},
            show_help ? (Rectangle){sw - 306.0f, 16, 290, 46 + 10 * 22.0f}
                      : (Rectangle){sw - 110.0f, 16, 94, 30},
            {sw - 256.0f, sh - 176.0f, 240, 160},
            {16, sh - 118.0f, 400, 102},
        };
        draw_labels(spots, n_spots, places, n_places, show_places, &view, cards, 4);

        /* the cell under the mouse: outline it (when zoomed in) and describe it */
        Vector2 mouse = GetMousePosition();
        int hr = (int)floorf((mouse.y - view.oy) / view.scale);
        int hc = (int)floorf((mouse.x - view.ox) / view.scale);
        if (hr >= 0 && hr < g.rows && hc >= 0 && hc < g.cols) {
            if (view.scale >= 6.0f)
                DrawRectangleLinesEx((Rectangle){view.ox + hc * view.scale,
                                                 view.oy + hr * view.scale,
                                                 view.scale, view.scale}, 2.0f, WHITE);
            draw_probe(sh, &g, &geo, spots, n_spots, places, n_places, hr, hc,
                       sim_depth(s)[(size_t)hr * g.cols + hc], a.threshold);
        }

        Status st = {sc, sim_time_s(s), rain_end, rain_end + POST_RAIN_S, running, paused,
                     sim_raining(s), flooded, spf, a.threshold,
                     g.cell_size_m * g.cell_size_m / 1e6f, view.scale / fit.scale};
        draw_status(&st);
        draw_help(sw, show_help);
        draw_legend(sw, sh, a.threshold, n_spots, show_base);
        EndDrawing();
    }

    unload_fonts();
    if (base.id)
        UnloadTexture(base);
    UnloadTexture(tex);
    CloseWindow();
    sim_destroy(s);
    free(shade);
    free(rgba);
    grid_free(&g);
    return 0;
}
