/* test_sim.c - checks for the water model (run with `make test`).
 * The timing test uses data/grid.bin + data/grid.meta if they exist (from
 * scripts/prepare_map.py; real or synthetic, see the source= line), otherwise a
 * built-in synthetic grid of the same size as the Bengaluru bbox. */
#define _POSIX_C_SOURCE 200809L
#include "sim.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static int failures = 0;

#define CHECK(cond, ...)                                   \
    do {                                                   \
        if (cond) {                                        \
            printf("  ok    ");                            \
        } else {                                           \
            printf("  FAIL  ");                            \
            failures++;                                    \
        }                                                  \
        printf(__VA_ARGS__);                               \
        printf("\n");                                      \
    } while (0)

static double now_s(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec * 1e-9;
}

static Grid make_grid(int rows, int cols)
{
    Grid g;
    g.rows = rows;
    g.cols = cols;
    g.cell_size_m = 30.0f;
    g.height = calloc((size_t)rows * cols, sizeof(float));
    return g;
}

/* Flat plane at 900 m with a round bowl (depth `depth` m, radius `rad` cells) in the middle. */
static Grid make_bowl(int n, float rad, float depth)
{
    Grid g = make_grid(n, n);
    for (int r = 0; r < n; r++)
        for (int c = 0; c < n; c++) {
            float dr = r - (n - 1) / 2.0f, dc = c - (n - 1) / 2.0f;
            float q = (dr * dr + dc * dc) / (rad * rad);
            g.height[r * n + c] = 900.0f - (q < 1.0f ? depth * (1.0f - q) : 0.0f);
        }
    return g;
}

/* Rolling hills + a few bowls + a valley; same idea as prepare_map.py --synthetic. */
static Grid make_hills(int rows, int cols)
{
    Grid g = make_grid(rows, cols);
    const float bowls[4][4] = { /* row frac, col frac, radius cells, depth m */
        {0.30f, 0.25f, 40, 6}, {0.65f, 0.40f, 60, 8}, {0.45f, 0.75f, 30, 5}, {0.80f, 0.80f, 50, 4}};
    for (int r = 0; r < rows; r++)
        for (int c = 0; c < cols; c++) {
            float y = (float)r / rows, x = (float)c / cols;
            float hgt = 920.0f - 25.0f * y - 10.0f * x;
            hgt += 8.0f * sinf(6.1f * x + 1.3f) * sinf(5.3f * y + 0.4f);
            hgt += 3.0f * sinf(17.0f * x + 3.0f * y) * cosf(13.0f * y - 2.0f * x);
            float vx = 0.5f + 0.15f * sinf(4.0f * y);         /* valley centre line */
            float dv = (x - vx) * cols / 40.0f;
            hgt -= 12.0f * expf(-dv * dv);
            for (int b = 0; b < 4; b++) {
                float dr = r - bowls[b][0] * rows, dc = c - bowls[b][1] * cols;
                float q = (dr * dr + dc * dc) / (bowls[b][2] * bowls[b][2]);
                if (q < 1.0f)
                    hgt -= bowls[b][3] * (1.0f - q) * (1.0f - q);
            }
            g.height[(size_t)r * cols + c] = hgt;
        }
    return g;
}

static int same_stats(SimStats a, SimStats b)
{
    return a.steps == b.steps && a.rain_m3 == b.rain_m3 && a.outflow_m3 == b.outflow_m3 &&
           a.stored_m3 == b.stored_m3 && a.flooded_cells == b.flooded_cells;
}

static double mass_err(SimStats st)
{
    return fabs(st.rain_m3 - st.outflow_m3 - st.stored_m3) / st.rain_m3;
}

static void print_stats(const char *name, SimStats st)
{
    printf("        %s: steps=%d rain=%.4g outflow=%.4g stored=%.4g flooded=%d mass_err=%.2e\n",
           name, st.steps, st.rain_m3, st.outflow_m3, st.stored_m3, st.flooded_cells,
           mass_err(st));
}

static SimStats run(const Grid *g, Scenario sc, float thr, int32_t **fc, float **md)
{
    size_t n = (size_t)g->rows * g->cols;
    *fc = calloc(n, sizeof **fc);
    *md = calloc(n, sizeof **md);
    SimState *s = sim_create(g);
    SimStats st = sim_run_scenario(s, sc, thr, *fc, *md);
    sim_destroy(s);
    return st;
}

static void test_flat(void)
{
    printf("[1] flat plane, light storm: mass conserved, nothing floods\n");
    Grid g = make_grid(40, 40);
    for (int i = 0; i < 40 * 40; i++)
        g.height[i] = 900.0f;
    int32_t *fc;
    float *md;
    SimStats st = run(&g, (Scenario){10.0f, 1.0f}, 0.3f, &fc, &md);
    print_stats("flat 10mm/h 1h", st);
    CHECK(mass_err(st) < 1e-4, "mass error %.2e < 1e-4", mass_err(st));
    CHECK(st.flooded_cells == 0, "no flooded cells on a flat plane");
    free(fc); free(md); grid_free(&g);
}

static void test_bowl(void)
{
    printf("[2] bowl collects water\n");
    Grid g = make_bowl(81, 25.0f, 3.0f);
    int32_t *fc;
    float *md;
    SimStats st = run(&g, (Scenario){100.0f, 6.0f}, 0.3f, &fc, &md);
    print_stats("bowl heavy 100mm/h 6h", st);
    int centre = 40 * 81 + 40;
    CHECK(st.flooded_cells > 0, "heavy storm floods the bowl (%d cells)", st.flooded_cells);
    CHECK(fc[centre] == 1, "bowl centre flooded");
    CHECK(fc[0] == 0, "map corner not flooded");
    CHECK(md[centre] > 0.3f, "peak depth at bowl centre %.3f m", md[centre]);
    free(fc); free(md);

    st = run(&g, (Scenario){3.0f, 1.0f}, 0.3f, &fc, &md);
    print_stats("bowl very light 3mm/h 1h", st);
    CHECK(st.flooded_cells == 0, "light storm floods nothing (%d cells)", st.flooded_cells);
    CHECK(st.stored_m3 > 0.0, "but water still pools in the bowl (%.3g m3)", st.stored_m3);
    free(fc); free(md); grid_free(&g);
}

static void test_mass(void)
{
    printf("[3] mass conservation on a synthetic grid (300x300)\n");
    Grid g = make_hills(300, 300);
    const Scenario sc[3] = {{10.0f, 1.0f}, {55.0f, 3.5f}, {100.0f, 6.0f}};
    for (int k = 0; k < 3; k++) {
        int32_t *fc;
        float *md;
        SimStats st = run(&g, sc[k], 0.3f, &fc, &md);
        char name[64];
        snprintf(name, sizeof name, "%.0fmm/h %.1fh", sc[k].intensity_mm_hr, sc[k].duration_hr);
        print_stats(name, st);
        CHECK(mass_err(st) < 1e-4, "mass error %.2e < 1e-4", mass_err(st));
        free(fc); free(md);
    }
    grid_free(&g);
}

static void test_determinism(void)
{
    printf("[4] determinism\n");
    Grid g = make_hills(200, 220);
    size_t n = (size_t)g.rows * g.cols;
    int32_t *fc1, *fc2;
    float *md1, *md2;
    Scenario sc = {70.0f, 2.5f};
    SimStats a = run(&g, sc, 0.3f, &fc1, &md1);
    SimStats b = run(&g, sc, 0.3f, &fc2, &md2);
    CHECK(memcmp(fc1, fc2, n * sizeof *fc1) == 0, "flood_count identical");
    CHECK(memcmp(md1, md2, n * sizeof *md1) == 0, "max_depth identical");
    CHECK(same_stats(a, b), "stats identical");
    /* reusing one SimState must give the same answer as a fresh one */
    SimState *s = sim_create(&g);
    memset(fc2, 0, n * sizeof *fc2);
    memset(md2, 0, n * sizeof *md2);
    sim_run_scenario(s, (Scenario){20.0f, 1.0f}, 0.3f, fc2, md2);
    memset(fc2, 0, n * sizeof *fc2);
    memset(md2, 0, n * sizeof *md2);
    SimStats c = sim_run_scenario(s, sc, 0.3f, fc2, md2);
    sim_destroy(s);
    CHECK(same_stats(a, c) && memcmp(fc1, fc2, n * sizeof *fc1) == 0 &&
          memcmp(md1, md2, n * sizeof *md1) == 0, "reused SimState gives identical results");
    free(fc1); free(fc2); free(md1); free(md2); grid_free(&g);
}

static void test_timing(void)
{
    printf("[5] timing of one storm on the full-size grid\n");
    Grid g;
    const char *what;
    char src[256] = "unknown";
    if (grid_load("data/grid.bin", "data/grid.meta", &g) == 0) {
        FILE *f = fopen("data/grid.meta", "r");
        char line[256];
        while (f && fgets(line, sizeof line, f))
            if (strncmp(line, "source=", 7) == 0) {
                snprintf(src, sizeof src, "%s", line + 7);
                src[strcspn(src, "\r\n")] = 0;
            }
        if (f)
            fclose(f);
        what = "data/grid.bin";
    } else {
        printf("        data/grid.bin not found: using the built-in synthetic grid\n");
        g = make_hills(1116, 1188);
        snprintf(src, sizeof src, "built-in synthetic (test_sim.c)");
        what = "built-in grid";
    }
    size_t n = (size_t)g.rows * g.cols;
    int32_t *fc = calloc(n, sizeof *fc);
    float *md = calloc(n, sizeof *md);
    SimState *s = sim_create(&g);
    const Scenario sc[3] = {{10.0f, 1.0f}, {55.0f, 3.5f}, {100.0f, 6.0f}};
    for (int k = 0; k < 3; k++) {
        double t0 = now_s();
        SimStats st = sim_run_scenario(s, sc[k], 0.3f, fc, md);
        double dt = now_s() - t0;
        printf("        %s (%dx%d, source: %s)\n", what, g.rows, g.cols, src);
        printf("        storm %.0f mm/h x %.1f h: %.2f s, %d steps (%.2f ms/step), flooded=%d, "
               "mass_err=%.2e\n", sc[k].intensity_mm_hr, sc[k].duration_hr, dt, st.steps,
               1000.0 * dt / st.steps, st.flooded_cells, mass_err(st));
        CHECK(mass_err(st) < 1e-4, "mass error %.2e < 1e-4", mass_err(st));
    }
    sim_destroy(s);
    free(fc); free(md); grid_free(&g);
}

int main(int argc, char **argv)
{
    int timing = !(argc > 1 && strcmp(argv[1], "--no-timing") == 0);
    test_flat();
    test_bowl();
    test_mass();
    test_determinism();
    if (timing)
        test_timing();
    if (failures) {
        printf("%d check(s) FAILED\n", failures);
        return 1;
    }
    printf("all checks passed\n");
    return 0;
}
