/* main_serial.c - serial baseline: runs every scenario on one process and writes the
 * same five output files as flood_mpi (contracts C3 and C4). No MPI here. */
#define _POSIX_C_SOURCE 200809L
#include "sim.h"

#include <errno.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>

typedef struct {
    const char *grid, *meta, *out;
    int n_int, n_dur, limit;
    double int_min, int_max, dur_min, dur_max, threshold;
} Args;

static double now_s(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec * 1e-9;
}

static void usage(void)
{
    fprintf(stderr,
            "usage: flood_serial --grid data/grid.bin --meta data/grid.meta\n"
            "         [--n-intensity 20] [--n-duration 20]\n"
            "         [--intensity-min 10] [--intensity-max 100]   (mm/hr)\n"
            "         [--duration-min 1] [--duration-max 6]        (hours)\n"
            "         [--threshold 0.3] [--mode dynamic|static (ignored)]\n"
            "         [--limit 0] [--out results/]\n");
}

static int parse_args(int argc, char **argv, Args *a)
{
    *a = (Args){"data/grid.bin", "data/grid.meta", "results/", 20, 20, 0,
                10.0, 100.0, 1.0, 6.0, 0.3};
    for (int i = 1; i < argc; i++) {
        const char *k = argv[i];
        if (i + 1 >= argc) {
            fprintf(stderr, "missing value for %s\n", k);
            return -1;
        }
        const char *v = argv[++i];
        if (!strcmp(k, "--grid")) a->grid = v;
        else if (!strcmp(k, "--meta")) a->meta = v;
        else if (!strcmp(k, "--out")) a->out = v;
        else if (!strcmp(k, "--n-intensity")) a->n_int = atoi(v);
        else if (!strcmp(k, "--n-duration")) a->n_dur = atoi(v);
        else if (!strcmp(k, "--intensity-min")) a->int_min = atof(v);
        else if (!strcmp(k, "--intensity-max")) a->int_max = atof(v);
        else if (!strcmp(k, "--duration-min")) a->dur_min = atof(v);
        else if (!strcmp(k, "--duration-max")) a->dur_max = atof(v);
        else if (!strcmp(k, "--threshold")) a->threshold = atof(v);
        else if (!strcmp(k, "--limit")) a->limit = atoi(v);
        else if (!strcmp(k, "--mode")) { /* serial runner ignores the mode */ }
        else {
            fprintf(stderr, "unknown option %s\n", k);
            return -1;
        }
    }
    if (a->n_int < 1 || a->n_dur < 1 || a->limit < 0) {
        fprintf(stderr, "--n-intensity and --n-duration must be >= 1, --limit >= 0\n");
        return -1;
    }
    return 0;
}

/* Contract C3: evenly spaced, both ends included, one value = the minimum. */
static float spaced(double lo, double hi, int n, int i)
{
    if (n == 1)
        return (float)lo;
    return (float)(lo + (hi - lo) * i / (n - 1));
}

/* mkdir -p */
static int make_dirs(const char *path)
{
    char buf[1024];
    snprintf(buf, sizeof buf, "%s", path);
    size_t len = strlen(buf);
    for (size_t i = 1; i <= len; i++) {
        if (buf[i] == '/' || buf[i] == '\0') {
            char saved = buf[i];
            buf[i] = '\0';
            if (mkdir(buf, 0755) != 0 && errno != EEXIST) {
                fprintf(stderr, "cannot create directory %s\n", buf);
                return -1;
            }
            buf[i] = saved;
        }
    }
    return 0;
}

static FILE *open_out(const char *dir, const char *name, const char *mode)
{
    char path[1100];
    size_t len = strlen(dir);
    snprintf(path, sizeof path, "%s%s%s", dir, (len && dir[len - 1] == '/') ? "" : "/", name);
    FILE *f = fopen(path, mode);
    if (!f)
        fprintf(stderr, "cannot write %s\n", path);
    return f;
}

static int write_floats(const char *dir, const char *name, const float *v, size_t n)
{
    FILE *f = open_out(dir, name, "wb");
    if (!f)
        return -1;
    size_t w = fwrite(v, sizeof *v, n, f);
    fclose(f);
    return w == n ? 0 : -1;
}

typedef struct {
    float intensity, duration;
    SimStats st;
    double runtime;
} Row;

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
    const size_t ncell = (size_t)g.rows * g.cols;

    int total = a.n_int * a.n_dur;
    int nrun = (a.limit > 0 && a.limit < total) ? a.limit : total;

    int32_t *flood_count = calloc(ncell, sizeof *flood_count);
    float *max_depth = calloc(ncell, sizeof *max_depth);
    float *freq = malloc(ncell * sizeof *freq);
    Row *rows = calloc((size_t)nrun, sizeof *rows);
    SimState *s = sim_create(&g);
    if (!flood_count || !max_depth || !freq || !rows || !s) {
        fprintf(stderr, "out of memory\n");
        return 1;
    }
    if (make_dirs(a.out) != 0)
        return 1;

    printf("flood_serial: grid %dx%d, %d of %d scenarios, threshold %.3g m\n",
           g.rows, g.cols, nrun, total, a.threshold);

    double t_start = now_s();
    double busy = 0.0;
    for (int id = 0; id < nrun; id++) {
        int ii = id / a.n_dur, id_ = id % a.n_dur;
        Scenario sc = {spaced(a.int_min, a.int_max, a.n_int, ii),
                       spaced(a.dur_min, a.dur_max, a.n_dur, id_)};
        double t0 = now_s();
        SimStats st = sim_run_scenario(s, sc, (float)a.threshold, flood_count, max_depth);
        double dt = now_s() - t0;
        busy += dt;
        rows[id] = (Row){sc.intensity_mm_hr, sc.duration_hr, st, dt};
        printf("  scenario %4d: %6.2f mm/h x %5.3f h  steps=%6d flooded=%8d  %.2f s\n", id,
               sc.intensity_mm_hr, sc.duration_hr, st.steps, st.flooded_cells, dt);
        fflush(stdout);
    }
    double wall = now_s() - t_start;

    for (size_t i = 0; i < ncell; i++)
        freq[i] = (float)flood_count[i] / (float)nrun;

    int err = 0;
    err |= write_floats(a.out, "freq.bin", freq, ncell);
    err |= write_floats(a.out, "maxdepth.bin", max_depth, ncell);

    const double cell_km2 = (double)g.cell_size_m * g.cell_size_m / 1e6;
    FILE *f = open_out(a.out, "scenarios.csv", "w");
    if (f) {
        fprintf(f, "id,intensity_mm_hr,duration_hr,flooded_cells,flooded_area_km2,runtime_s,"
                   "rank,steps,mass_error_rel\n");
        for (int id = 0; id < nrun; id++) {
            const Row *r = &rows[id];
            double merr = r->st.rain_m3 > 0
                ? fabs(r->st.rain_m3 - r->st.outflow_m3 - r->st.stored_m3) / r->st.rain_m3 : 0.0;
            fprintf(f, "%d,%.6g,%.6g,%d,%.6f,%.6f,%d,%d,%.6e\n", id, r->intensity, r->duration,
                    r->st.flooded_cells, r->st.flooded_cells * cell_km2, r->runtime, 0,
                    r->st.steps, merr);
        }
        fclose(f);
    } else {
        err = 1;
    }
    f = open_out(a.out, "timings.csv", "w");
    if (f) {
        fprintf(f, "rank,scenarios_run,busy_time_s\n0,%d,%.6f\n", nrun, busy);
        fclose(f);
    } else {
        err = 1;
    }
    f = open_out(a.out, "run_info.csv", "w");
    if (f) {
        fprintf(f, "mode,nprocs,n_scenarios,wall_time_s,rows,cols\nserial,1,%d,%.6f,%d,%d\n",
                nrun, wall, g.rows, g.cols);
        fclose(f);
    } else {
        err = 1;
    }

    printf("flood_serial: %d scenarios in %.2f s, results in %s\n", nrun, wall, a.out);
    sim_destroy(s);
    free(flood_count); free(max_depth); free(freq); free(rows);
    grid_free(&g);
    return err ? 1 : 0;
}
