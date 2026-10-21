/* mpi_main.c - [M2] the MPI engine: runs every rain scenario on many processes and writes the
 * same five output files as flood_serial (contracts C3 and C4).
 *
 * Parallel design (storms are independent, so whole storms are shared out):
 *   np == 1        rank 0 simulates every scenario itself (serial baseline for the speed-up).
 *   dynamic mode   rank 0 is a coordinator that never simulates. Each worker (ranks 1..np-1)
 *                  sends a READY message carrying the result of its previous storm and gets
 *                  back the id of the next storm, or -1 = stop.
 *   static mode    worker w gets one fixed contiguous block of ids up front, no messages while
 *                  running; the per-storm records are gathered to rank 0 at the end.
 * Combining (all cases): MPI_Reduce(SUM) of per-cell flood counts, MPI_Reduce(MAX) of per-cell
 * peak depths, MPI_Gather of per-rank busy time and scenario count.
 *
 * Every rank keeps its own copy of the grid and its own SimState, so storms need no
 * communication at all while they run. */
#define _POSIX_C_SOURCE 200809L
#include "scenarios.h"
#include "sim.h"

#include <mpi.h>

#include <errno.h>
#include <limits.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

/* ---------------------------------------------------------------- message layout ----------
 * Tags of the dynamic-mode protocol:
 *   TAG_READY  worker -> rank 0, REC_LEN doubles (one result record, layout below).
 *              The first READY of a worker carries id = -1 (no result yet).
 *   TAG_WORK   rank 0 -> worker, 1 int: the next scenario id, or -1 = no work left, stop.
 *
 * Result record = REC_LEN doubles (doubles hold every int value used here exactly).
 * The same record is used in dynamic mode (inside READY) and in static mode (MPI_Gatherv). */
enum { TAG_READY = 1, TAG_WORK = 2 };
enum {
    REC_ID = 0,          /* scenario id, or -1 in a worker's first READY */
    REC_RANK,            /* rank that ran it */
    REC_FLOODED,         /* SimStats.flooded_cells */
    REC_RUNTIME,         /* seconds inside sim_run_scenario (MPI_Wtime) */
    REC_STEPS,           /* SimStats.steps */
    REC_MASS_ERR,        /* |rain - outflow - stored| / rain */
    REC_LEN
};
#define STOP_ID (-1)

/* ---------------------------------------------------------------- settings ----------------
 * Rank 0 parses the command line and broadcasts the settings as three fixed-size arrays
 * (ints, doubles, chars), so every rank sees exactly the same values. */
#define PATH_LEN 512
enum { I_N_INT, I_N_DUR, I_LIMIT, I_MODE, I_OK, N_ISET };
enum { D_INT_MIN, D_INT_MAX, D_DUR_MIN, D_DUR_MAX, D_THRESHOLD, D_LOSS, N_DSET };
enum { P_GRID, P_META, P_OUT, N_PSET };
enum { MODE_DYNAMIC = 0, MODE_STATIC = 1 };

typedef struct {
    int    iv[N_ISET];
    double dv[N_DSET];
    char   path[N_PSET][PATH_LEN];
} Settings;

static void usage(void)
{
    fprintf(stderr,
            "usage: mpirun -np N flood_mpi --grid data/grid.bin --meta data/grid.meta\n"
            "         [--n-intensity 20] [--n-duration 20]\n"
            "         [--intensity-min 10] [--intensity-max 100]   (mm/hr)\n"
            "         [--duration-min 1] [--duration-max 6]        (hours)\n"
            "         [--threshold 0.3] [--mode dynamic|static]\n"
            "         [--loss 0]                                (mm/hr soaked up)\n"
            "         [--limit 0] [--out results/]\n");
}

static int parse_int(const char *k, const char *v, int *out)
{
    char *end;
    errno = 0;
    long x = strtol(v, &end, 10);
    if (errno || end == v || *end || x < INT_MIN || x > INT_MAX) {
        fprintf(stderr, "flood_mpi: bad integer value '%s' for %s\n", v, k);
        return -1;
    }
    *out = (int)x;
    return 0;
}

static int parse_double(const char *k, const char *v, double *out)
{
    char *end;
    errno = 0;
    double x = strtod(v, &end);
    if (errno || end == v || *end || !isfinite(x)) {
        fprintf(stderr, "flood_mpi: bad number '%s' for %s\n", v, k);
        return -1;
    }
    *out = x;
    return 0;
}

static int set_path(Settings *s, int which, const char *k, const char *v)
{
    if (strlen(v) >= PATH_LEN) {
        fprintf(stderr, "flood_mpi: path for %s is longer than %d characters\n", k, PATH_LEN - 1);
        return -1;
    }
    strcpy(s->path[which], v);
    return 0;
}

/* Same flags and defaults as main_serial.c. Returns 0 = ok. Only rank 0 calls this. */
static int parse_args(int argc, char **argv, Settings *s)
{
    memset(s, 0, sizeof *s);
    s->iv[I_N_INT] = 20;
    s->iv[I_N_DUR] = 20;
    s->iv[I_LIMIT] = 0;
    s->iv[I_MODE] = MODE_DYNAMIC;
    s->dv[D_INT_MIN] = 10.0;
    s->dv[D_INT_MAX] = 100.0;
    s->dv[D_DUR_MIN] = 1.0;
    s->dv[D_DUR_MAX] = 6.0;
    s->dv[D_THRESHOLD] = 0.3;
    s->dv[D_LOSS] = 0.0;
    strcpy(s->path[P_GRID], "data/grid.bin");
    strcpy(s->path[P_META], "data/grid.meta");
    strcpy(s->path[P_OUT], "results/");

    for (int i = 1; i < argc; i++) {
        const char *k = argv[i];
        if (i + 1 >= argc) {
            fprintf(stderr, "flood_mpi: missing value for %s\n", k);
            return -1;
        }
        const char *v = argv[++i];
        int rc;
        if (!strcmp(k, "--grid")) rc = set_path(s, P_GRID, k, v);
        else if (!strcmp(k, "--meta")) rc = set_path(s, P_META, k, v);
        else if (!strcmp(k, "--out")) rc = set_path(s, P_OUT, k, v);
        else if (!strcmp(k, "--n-intensity")) rc = parse_int(k, v, &s->iv[I_N_INT]);
        else if (!strcmp(k, "--n-duration")) rc = parse_int(k, v, &s->iv[I_N_DUR]);
        else if (!strcmp(k, "--limit")) rc = parse_int(k, v, &s->iv[I_LIMIT]);
        else if (!strcmp(k, "--intensity-min")) rc = parse_double(k, v, &s->dv[D_INT_MIN]);
        else if (!strcmp(k, "--intensity-max")) rc = parse_double(k, v, &s->dv[D_INT_MAX]);
        else if (!strcmp(k, "--duration-min")) rc = parse_double(k, v, &s->dv[D_DUR_MIN]);
        else if (!strcmp(k, "--duration-max")) rc = parse_double(k, v, &s->dv[D_DUR_MAX]);
        else if (!strcmp(k, "--threshold")) rc = parse_double(k, v, &s->dv[D_THRESHOLD]);
        else if (!strcmp(k, "--loss")) rc = parse_double(k, v, &s->dv[D_LOSS]);
        else if (!strcmp(k, "--mode")) {
            rc = 0;
            if (!strcmp(v, "dynamic")) s->iv[I_MODE] = MODE_DYNAMIC;
            else if (!strcmp(v, "static")) s->iv[I_MODE] = MODE_STATIC;
            else {
                fprintf(stderr, "flood_mpi: --mode must be dynamic or static, not '%s'\n", v);
                rc = -1;
            }
        } else {
            fprintf(stderr, "flood_mpi: unknown option %s\n", k);
            rc = -1;
        }
        if (rc != 0)
            return -1;
    }
    if (s->iv[I_N_INT] < 1 || s->iv[I_N_DUR] < 1 || s->iv[I_LIMIT] < 0) {
        fprintf(stderr, "flood_mpi: --n-intensity and --n-duration must be >= 1, --limit >= 0\n");
        return -1;
    }
    if (s->iv[I_N_INT] > 100000 / s->iv[I_N_DUR]) {
        fprintf(stderr, "flood_mpi: more than 100000 scenarios requested\n");
        return -1;
    }
    if (s->dv[D_DUR_MIN] <= 0.0 || s->dv[D_DUR_MAX] < s->dv[D_DUR_MIN] ||
        s->dv[D_INT_MIN] < 0.0 || s->dv[D_INT_MAX] < s->dv[D_INT_MIN]) {
        fprintf(stderr, "flood_mpi: need 0 < duration-min <= duration-max and "
                        "0 <= intensity-min <= intensity-max\n");
        return -1;
    }
    return 0;
}

/* ---------------------------------------------------------------- output helpers ----------
 * Same behaviour and formats as main_serial.c. */
static int make_dirs(const char *path)   /* mkdir -p */
{
    char buf[1024];
    snprintf(buf, sizeof buf, "%s", path);
    size_t len = strlen(buf);
    for (size_t i = 1; i <= len; i++) {
        if (buf[i] == '/' || buf[i] == '\0') {
            char saved = buf[i];
            buf[i] = '\0';
            if (mkdir(buf, 0755) != 0 && errno != EEXIST) {
                fprintf(stderr, "flood_mpi: cannot create directory %s\n", buf);
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
        fprintf(stderr, "flood_mpi: cannot write %s\n", path);
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

/* Write the five files of contract C4. Rank 0 only. Returns 0 = ok. */
static int write_outputs(const Settings *s, const Grid *g, const ScenarioList *L,
                         const float *freq, const float *max_depth, const double *rec,
                         const double *rank_stats, int nprocs, double wall)
{
    const char *out = s->path[P_OUT];
    const size_t ncell = (size_t)g->rows * g->cols;
    int err = 0;
    err |= write_floats(out, "freq.bin", freq, ncell);
    err |= write_floats(out, "maxdepth.bin", max_depth, ncell);

    const double cell_km2 = (double)g->cell_size_m * g->cell_size_m / 1e6;
    FILE *f = open_out(out, "scenarios.csv", "w");
    if (f) {
        fprintf(f, "id,intensity_mm_hr,duration_hr,flooded_cells,flooded_area_km2,runtime_s,"
                   "rank,steps,mass_error_rel\n");
        for (int id = 0; id < L->n; id++) {          /* rec[] is indexed by id: sorted */
            const double *r = &rec[(size_t)id * REC_LEN];
            int flooded = (int)r[REC_FLOODED];
            fprintf(f, "%d,%.6g,%.6g,%d,%.6f,%.6f,%d,%d,%.6e\n", id,
                    L->sc[id].intensity_mm_hr, L->sc[id].duration_hr, flooded,
                    flooded * cell_km2, r[REC_RUNTIME], (int)r[REC_RANK], (int)r[REC_STEPS],
                    r[REC_MASS_ERR]);
        }
        fclose(f);
    } else {
        err = 1;
    }

    f = open_out(out, "timings.csv", "w");
    if (f) {
        fprintf(f, "rank,scenarios_run,busy_time_s\n");
        for (int r = 0; r < nprocs; r++)
            fprintf(f, "%d,%d,%.6f\n", r, (int)rank_stats[2 * r], rank_stats[2 * r + 1]);
        fclose(f);
    } else {
        err = 1;
    }

    f = open_out(out, "run_info.csv", "w");
    if (f) {
        fprintf(f, "mode,nprocs,n_scenarios,wall_time_s,rows,cols\n%s,%d,%d,%.6f,%d,%d\n",
                s->iv[I_MODE] == MODE_STATIC ? "static" : "dynamic", nprocs, L->n, wall,
                g->rows, g->cols);
        fclose(f);
    } else {
        err = 1;
    }
    return err ? -1 : 0;
}

/* ---------------------------------------------------------------- running storms ----------
 * Everything one rank needs to run storms locally. */
typedef struct {
    int rank;
    const ScenarioList *L;
    float threshold;
    float loss;               /* --loss, mm/h */
    SimState *sim;
    int32_t *flood_count;     /* accumulated over this rank's storms */
    float *max_depth;         /* accumulated over this rank's storms */
    double busy;              /* seconds spent inside sim_run_scenario */
    int n_run;                /* storms this rank ran */
} Worker;

/* --loss L (mm/h, default 0): a constant loss rate (the "phi index"): the ground soaks up
   L mm of rain per hour, so the model gets max(0, intensity - L). scenarios.csv still lists
   the real intensity. flood_serial and flood_mpi apply it the same way (float arithmetic),
   so their results stay bit-identical. */
/* Run one storm and fill a result record. */
static void run_one(Worker *w, int id, double *rec)
{
    Scenario sc = w->L->sc[id];
    Scenario eff = sc;
    eff.intensity_mm_hr = fmaxf(0.0f, sc.intensity_mm_hr - w->loss);
    double t0 = MPI_Wtime();   /* MPI_Wtime: portable wall clock, the busy time of this storm */
    SimStats st = sim_run_scenario(w->sim, eff, w->threshold, w->flood_count, w->max_depth);
    double dt = MPI_Wtime() - t0;
    w->busy += dt;
    w->n_run++;

    rec[REC_ID] = id;
    rec[REC_RANK] = w->rank;
    rec[REC_FLOODED] = st.flooded_cells;
    rec[REC_RUNTIME] = dt;
    rec[REC_STEPS] = st.steps;
    rec[REC_MASS_ERR] = st.rain_m3 > 0
        ? fabs(st.rain_m3 - st.outflow_m3 - st.stored_m3) / st.rain_m3 : 0.0;

    printf("  rank %2d: scenario %4d  %6.2f mm/h x %5.3f h  steps=%5d flooded=%8d  %.2f s\n",
           w->rank, id, sc.intensity_mm_hr, sc.duration_hr, st.steps, st.flooded_cells, dt);
    fflush(stdout);
}

/* np == 1: rank 0 runs everything; records go straight into rec[]. */
static void run_serial(Worker *w, double *rec)
{
    for (int id = 0; id < w->L->n; id++)
        run_one(w, id, &rec[(size_t)id * REC_LEN]);
}

/* Dynamic mode, rank 0: hand out ids one by one, store each returned record in rec[]. */
static void coordinator(int nprocs, int n_scen, double *rec)
{
    int next = 0;                 /* next id to hand out */
    int active = nprocs - 1;      /* workers not yet told to stop */
    double msg[REC_LEN];
    MPI_Status status;
    while (active > 0) {
        /* MPI_Recv from MPI_ANY_SOURCE: serve whichever worker finishes first (dynamic balance) */
        MPI_Recv(msg, REC_LEN, MPI_DOUBLE, MPI_ANY_SOURCE, TAG_READY, MPI_COMM_WORLD, &status);
        int done_id = (int)msg[REC_ID];
        if (done_id >= 0)         /* not the worker's first request: keep its result */
            memcpy(&rec[(size_t)done_id * REC_LEN], msg, sizeof msg);

        int give = STOP_ID;
        if (next < n_scen)
            give = next++;
        else
            active--;             /* this worker gets -1 and leaves the loop */
        /* MPI_Send to status.MPI_SOURCE: reply to exactly the worker that asked */
        MPI_Send(&give, 1, MPI_INT, status.MPI_SOURCE, TAG_WORK, MPI_COMM_WORLD);
    }
}

/* Dynamic mode, ranks 1..np-1: READY(previous result) -> id -> run -> repeat until id = -1. */
static void dynamic_worker(Worker *w)
{
    double msg[REC_LEN];
    for (int k = 0; k < REC_LEN; k++)
        msg[k] = 0.0;
    msg[REC_ID] = STOP_ID;        /* first READY carries no result */
    msg[REC_RANK] = w->rank;
    for (;;) {
        /* MPI_Send READY: report the last result and ask rank 0 for more work */
        MPI_Send(msg, REC_LEN, MPI_DOUBLE, 0, TAG_READY, MPI_COMM_WORLD);
        int id;
        /* MPI_Recv from rank 0: the next scenario id (or -1 = stop); blocks until it arrives */
        MPI_Recv(&id, 1, MPI_INT, 0, TAG_WORK, MPI_COMM_WORLD, MPI_STATUS_IGNORE);
        if (id == STOP_ID)
            break;
        run_one(w, id, msg);
    }
}

/* Static mode: block of worker w (1..nworkers) = ids [start, start+count), sizes differ by
 * at most one. Every rank can compute every block, so nothing has to be sent beforehand. */
static void static_block(int n_scen, int nworkers, int w, int *start, int *count)
{
    int k = w - 1;
    int base = n_scen / nworkers, rem = n_scen % nworkers;
    *count = base + (k < rem ? 1 : 0);
    *start = k * base + (k < rem ? k : rem);
}

/* Static mode, all ranks: workers run their block, then MPI_Gatherv collects the records. */
static void run_static(Worker *w, int nprocs, double *rec_all)
{
    const int nworkers = nprocs - 1;
    const int n_scen = w->L->n;
    int start = 0, count = 0;
    double *mine = NULL;

    if (w->rank > 0) {
        static_block(n_scen, nworkers, w->rank, &start, &count);
        mine = malloc((size_t)(count > 0 ? count : 1) * REC_LEN * sizeof *mine);
        if (!mine) {
            fprintf(stderr, "flood_mpi: rank %d out of memory\n", w->rank);
            MPI_Abort(MPI_COMM_WORLD, 1);
        }
        for (int j = 0; j < count; j++)      /* no messages at all while storms run */
            run_one(w, start + j, &mine[(size_t)j * REC_LEN]);
    }

    /* Rank 0 knows every block, so it builds the receive counts/offsets itself. Blocks are
     * contiguous and in rank order, so the gathered records land already sorted by id. */
    int *counts = NULL, *displs = NULL;
    if (w->rank == 0) {
        counts = calloc((size_t)nprocs, sizeof *counts);
        displs = calloc((size_t)nprocs, sizeof *displs);
        if (!counts || !displs) {
            fprintf(stderr, "flood_mpi: rank 0 out of memory\n");
            MPI_Abort(MPI_COMM_WORLD, 1);
        }
        for (int r = 1; r < nprocs; r++) {
            int s0, c0;
            static_block(n_scen, nworkers, r, &s0, &c0);
            counts[r] = c0 * REC_LEN;          /* rank 0 sends 0 records */
            displs[r] = s0 * REC_LEN;
        }
    }
    /* MPI_Gatherv: workers hold different numbers of fixed-size records (blocks differ by 1) */
    MPI_Gatherv(mine, count * REC_LEN, MPI_DOUBLE,
                rec_all, counts, displs, MPI_DOUBLE, 0, MPI_COMM_WORLD);
    free(mine);
    free(counts);
    free(displs);
}

/* ---------------------------------------------------------------- main --------------------- */
int main(int argc, char **argv)
{
    /* MPI_Init: start MPI; every process runs this same program */
    MPI_Init(&argc, &argv);
    int rank, nprocs;
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);     /* who am I (0 = coordinator / root) */
    MPI_Comm_size(MPI_COMM_WORLD, &nprocs);   /* how many processes in total */

    /* 1. settings: rank 0 parses, everybody receives the same copy */
    Settings set;
    memset(&set, 0, sizeof set);
    if (rank == 0) {
        set.iv[I_OK] = parse_args(argc, argv, &set) == 0;
        if (set.iv[I_OK] && make_dirs(set.path[P_OUT]) != 0)
            set.iv[I_OK] = 0;
        if (!set.iv[I_OK])
            usage();
    }
    /* MPI_Bcast x3: the parsed settings (ints, doubles, fixed-size path strings) to every rank */
    MPI_Bcast(set.iv, N_ISET, MPI_INT, 0, MPI_COMM_WORLD);
    MPI_Bcast(set.dv, N_DSET, MPI_DOUBLE, 0, MPI_COMM_WORLD);
    MPI_Bcast(set.path, N_PSET * PATH_LEN, MPI_CHAR, 0, MPI_COMM_WORLD);
    if (!set.iv[I_OK]) {
        /* MPI_Abort: bad command line, stop every process with a non-zero exit code */
        if (rank == 0)
            fprintf(stderr, "flood_mpi: aborting because of the error above\n");
        MPI_Abort(MPI_COMM_WORLD, 2);
    }
    const int mode = set.iv[I_MODE];

    /* every rank builds the same scenario list from the settings: no list is ever sent */
    ScenarioSpec spec = {set.iv[I_N_INT], set.iv[I_N_DUR], set.dv[D_INT_MIN], set.dv[D_INT_MAX],
                         set.dv[D_DUR_MIN], set.dv[D_DUR_MAX], set.iv[I_LIMIT]};
    ScenarioList L;
    if (scenarios_build(&spec, &L) != 0) {
        fprintf(stderr, "flood_mpi: rank %d cannot build the scenario list\n", rank);
        MPI_Abort(MPI_COMM_WORLD, 1);  /* MPI_Abort: one rank failed, the others must not hang */
    }

    /* every rank loads its own copy of the grid (no grid is sent over MPI) */
    Grid g;
    if (grid_load(set.path[P_GRID], set.path[P_META], &g) != 0) {
        fprintf(stderr, "flood_mpi: rank %d cannot load grid %s / %s\n", rank,
                set.path[P_GRID], set.path[P_META]);
        MPI_Abort(MPI_COMM_WORLD, 1);  /* MPI_Abort: missing grid, stop everyone cleanly */
    }
    const size_t ncell = (size_t)g.rows * g.cols;
    if (ncell > (size_t)INT_MAX) {     /* MPI counts are int: the reduce needs ncell <= INT_MAX */
        fprintf(stderr, "flood_mpi: grid has %zu cells, more than an MPI count can hold\n", ncell);
        MPI_Abort(MPI_COMM_WORLD, 1);
    }

    /* all ranks (also rank 0, which may not simulate) need zeroed arrays for the reduce */
    int32_t *flood_count = calloc(ncell, sizeof *flood_count);
    float *max_depth = calloc(ncell, sizeof *max_depth);
    SimState *sim = sim_create(&g);
    double *rec = NULL;                /* rank 0: one record per scenario, indexed by id */
    if (rank == 0)
        rec = calloc((size_t)L.n * REC_LEN, sizeof *rec);
    if (!flood_count || !max_depth || !sim || (rank == 0 && !rec)) {
        fprintf(stderr, "flood_mpi: rank %d out of memory\n", rank);
        MPI_Abort(MPI_COMM_WORLD, 1);
    }

    Worker w = {rank, &L, (float)set.dv[D_THRESHOLD], (float)set.dv[D_LOSS], sim, flood_count,
                max_depth, 0.0, 0};

    if (rank == 0) {
        printf("flood_mpi: mode %s, np %d, grid %dx%d, %d of %d scenarios, threshold %.3g m\n",
               nprocs == 1 ? "single process" : (mode == MODE_STATIC ? "static" : "dynamic"),
               nprocs, g.rows, g.cols, L.n, L.total, set.dv[D_THRESHOLD]);
        fflush(stdout);
    }

    /* 2-4. the run. MPI_Barrier: everyone starts the clock together (grid loading excluded) */
    MPI_Barrier(MPI_COMM_WORLD);
    double t_start = MPI_Wtime();

    if (nprocs == 1)
        run_serial(&w, rec);
    else if (mode == MODE_DYNAMIC) {
        if (rank == 0)
            coordinator(nprocs, L.n, rec);
        else
            dynamic_worker(&w);
    } else {
        run_static(&w, nprocs, rec);
    }

    /* MPI_Barrier: the run ends when the slowest rank is done, so stop the clock after it */
    MPI_Barrier(MPI_COMM_WORLD);
    double wall = MPI_Wtime() - t_start;

    /* 5. combine the per-cell results on rank 0; MPI_IN_PLACE = rank 0 adds into its own array */
    double t_comb = MPI_Wtime();
    if (rank == 0) {
        /* MPI_Reduce SUM: total number of storms in which each cell flooded */
        MPI_Reduce(MPI_IN_PLACE, flood_count, (int)ncell, MPI_INT32_T, MPI_SUM, 0, MPI_COMM_WORLD);
        /* MPI_Reduce MAX: deepest water each cell ever saw, over all storms */
        MPI_Reduce(MPI_IN_PLACE, max_depth, (int)ncell, MPI_FLOAT, MPI_MAX, 0, MPI_COMM_WORLD);
    } else {
        MPI_Reduce(flood_count, NULL, (int)ncell, MPI_INT32_T, MPI_SUM, 0, MPI_COMM_WORLD);
        MPI_Reduce(max_depth, NULL, (int)ncell, MPI_FLOAT, MPI_MAX, 0, MPI_COMM_WORLD);
    }

    /* 6. per-rank statistics: {scenarios run, busy seconds} from every rank */
    double my_stats[2] = {(double)w.n_run, w.busy};
    double *rank_stats = NULL;
    if (rank == 0) {
        rank_stats = malloc((size_t)nprocs * 2 * sizeof *rank_stats);
        if (!rank_stats) {
            fprintf(stderr, "flood_mpi: rank 0 out of memory\n");
            MPI_Abort(MPI_COMM_WORLD, 1);
        }
    }
    /* MPI_Gather: rank 0 needs everyone's busy time and count for timings.csv and imbalance */
    MPI_Gather(my_stats, 2, MPI_DOUBLE, rank_stats, 2, MPI_DOUBLE, 0, MPI_COMM_WORLD);
    double comb = MPI_Wtime() - t_comb;

    /* 7. output, rank 0 only */
    int err = 0;
    if (rank == 0) {
        float *freq = malloc(ncell * sizeof *freq);
        if (!freq) {
            fprintf(stderr, "flood_mpi: rank 0 out of memory\n");
            MPI_Abort(MPI_COMM_WORLD, 1);
        }
        for (size_t i = 0; i < ncell; i++)    /* identical expression to main_serial.c */
            freq[i] = (float)flood_count[i] / (float)L.n;
        err = write_outputs(&set, &g, &L, freq, max_depth, rec, rank_stats, nprocs, wall) != 0;
        free(freq);

        /* summary; imbalance = max busy / mean busy over the ranks that simulate */
        int first = nprocs == 1 ? 0 : 1;
        double sum = 0.0, mx = 0.0;
        printf("flood_mpi: summary\n  mode %s, np %d, %d scenarios, wall %.3f s "
               "(combine %.3f s)\n",
               nprocs == 1 ? "single" : (mode == MODE_STATIC ? "static" : "dynamic"), nprocs,
               L.n, wall, comb);
        for (int r = 0; r < nprocs; r++) {
            double b = rank_stats[2 * r + 1];
            printf("  rank %2d: %4d scenarios, busy %8.3f s%s\n", r, (int)rank_stats[2 * r], b,
                   (r == 0 && nprocs > 1) ? "  (coordinator / root, does not simulate)" : "");
            if (r >= first) {
                sum += b;
                if (b > mx)
                    mx = b;
            }
        }
        double mean = sum / (nprocs - first);
        if (mean > 0)
            printf("  load imbalance (max busy / mean busy over workers) = %.3f\n", mx / mean);
        else
            printf("  load imbalance: n/a (no busy time)\n");
        printf("flood_mpi: results in %s\n", set.path[P_OUT]);
        fflush(stdout);
    }

    /* 8. clean up */
    free(rank_stats);
    free(rec);
    free(flood_count);
    free(max_depth);
    sim_destroy(sim);
    grid_free(&g);
    scenarios_free(&L);
    MPI_Finalize();                    /* MPI_Finalize: shut MPI down on every rank */
    return err ? 1 : 0;
}
