/* sim.c - deliberately simple, deterministic water-flow model (see sim.h).
 *
 * Scheme, one time step:
 *   1. Rain: while t < duration, every cell gets intensity * dt of water
 *      (the last rain step is shortened so the total rain is exact).
 *   2. Flow (two buffers: read h, write hn, so cell order does not matter):
 *      every wet cell (depth > SIM_DRY_EPS) looks at its 4 neighbours and computes the
 *      drop in water surface (ground + depth) to each lower one. It moves
 *          out = min(depth, SIM_FLOW_K * largest drop)
 *      and splits `out` between the lower neighbours in proportion to their drops.
 *      A cell on the map edge sees the outside as a dry neighbour at its own ground
 *      height (drop = its depth), so edge water drains off the map -> outflow_m3.
 *   3. Track the per-cell peak depth.
 *   A storm runs a fixed number of steps: the rain steps plus POST_RAIN_STEPS. There is no
 *   convergence test and no step cap (full ponds spill over their rims so slowly that
 *   waiting for the water to stop moving took tens of thousands of steps). The depth at the
 *   final step is the depth used for flood counting.
 *
 * Constants:
 *   SIM_DT_S       = 30 s    one step; a 1..6 h storm is 120..720 rain steps.
 *   POST_RAIN_STEPS = 240    drain window after the rain stops (2 h at dt = 30 s).
 *                            Total steps = ceil(duration / dt) + 240, i.e. 360..960.
 *   SIM_FLOW_K     = 0.25    at most 1/4 of the largest surface drop moves per step. This
 *                            is the stability limit of this 4-neighbour scheme (a cell is
 *                            never overfilled above its senders); do not raise it.
 *   The flow acts per STEP, not per second: dt only sets how much rain falls per step.
 *   Water speed is therefore fixed in cells per step, and the drain window is a model
 *   parameter, not physical time.
 *   SIM_DRY_EPS    = 1e-6 m  shallower cells are treated as dry and skipped.
 *
 * Only float/double arithmetic in a fixed loop order: results are bit-identical between
 * runs, and between flood_serial and flood_mpi (same source, same flags).
 */
#include "sim.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

#define SIM_DT_S        30.0
#define SIM_FLOW_K      0.25f
#define SIM_DRY_EPS     1e-6f
#define POST_RAIN_STEPS 240
/* When a cell drains completely it keeps this relative remainder, so float rounding of
   the split can never push its depth below zero. The remainder is far below SIM_DRY_EPS. */
#define SIM_DRAIN_KEEP  1e-6f

struct SimState {
    int rows, cols;
    size_t n;
    double cell_area_m2;
    const float *z;     /* ground height, owned by the Grid */
    float *h;           /* current depth */
    float *hn;          /* next depth */
    float *peak;        /* deepest water seen this storm */
    double dur_s;       /* rain duration in seconds */
    double rate_m_s;    /* rain in metres per second */
    int steps;
    int total_steps;    /* rain steps + POST_RAIN_STEPS */
    int done;
    double rain_m3;
    double outflow_m3;
};

SimState *sim_create(const Grid *g)
{
    SimState *s = calloc(1, sizeof *s);
    if (!s)
        return NULL;
    s->rows = g->rows;
    s->cols = g->cols;
    s->n = (size_t)g->rows * (size_t)g->cols;
    s->cell_area_m2 = (double)g->cell_size_m * (double)g->cell_size_m;
    s->z = g->height;
    s->h = calloc(s->n, sizeof *s->h);
    s->hn = calloc(s->n, sizeof *s->hn);
    s->peak = calloc(s->n, sizeof *s->peak);
    if (!s->h || !s->hn || !s->peak) {
        sim_destroy(s);
        return NULL;
    }
    s->done = 1;
    return s;
}

void sim_destroy(SimState *s)
{
    if (!s)
        return;
    free(s->h);
    free(s->hn);
    free(s->peak);
    free(s);
}

void sim_begin(SimState *s, Scenario sc)
{
    memset(s->h, 0, s->n * sizeof *s->h);
    memset(s->hn, 0, s->n * sizeof *s->hn);
    memset(s->peak, 0, s->n * sizeof *s->peak);
    s->dur_s = (double)sc.duration_hr * 3600.0;
    s->rate_m_s = (double)sc.intensity_mm_hr / 1000.0 / 3600.0;
    s->total_steps = (int)ceil(s->dur_s / SIM_DT_S) + POST_RAIN_STEPS;
    s->steps = 0;
    s->done = 0;
    s->rain_m3 = 0.0;
    s->outflow_m3 = 0.0;
}

/* Advance one time step. */
static void step_once(SimState *s)
{
    const int rows = s->rows, cols = s->cols;
    const size_t n = s->n;
    const float *z = s->z;
    float *h = s->h;
    float *hn = s->hn;

    /* 1. rain */
    double t = s->steps * SIM_DT_S;
    if (t < s->dur_s) {
        double secs = s->dur_s - t < SIM_DT_S ? s->dur_s - t : SIM_DT_S;
        float add = (float)(s->rate_m_s * secs);
        for (size_t i = 0; i < n; i++)
            h[i] += add;
        s->rain_m3 += (double)add * (double)n * s->cell_area_m2;
    }

    /* 2. flow */
    memcpy(hn, h, n * sizeof *hn);
    double edge_out = 0.0;
    for (int r = 0; r < rows; r++) {
        for (int c = 0; c < cols; c++) {
            const size_t i = (size_t)r * cols + c;
            const float hv = h[i];
            if (hv <= SIM_DRY_EPS)
                continue;
            const float zi = z[i];
            /* drops to N, S, W, E; outside the map = dry ground at this cell's height.
               (zi - zj) + (hi - hj) instead of (zi + hi) - (zj + hj): at ~900 m a float
               surface height is only good to ~6e-5 m, which would never settle. */
            float d[4];
            d[0] = r > 0        ? (zi - z[i - cols]) + (hv - h[i - cols]) : hv;
            d[1] = r < rows - 1 ? (zi - z[i + cols]) + (hv - h[i + cols]) : hv;
            d[2] = c > 0        ? (zi - z[i - 1]) + (hv - h[i - 1])       : hv;
            d[3] = c < cols - 1 ? (zi - z[i + 1]) + (hv - h[i + 1])       : hv;
            float sum = 0.0f, dmax = 0.0f;
            for (int k = 0; k < 4; k++) {
                if (d[k] > 0.0f) {
                    sum += d[k];
                    if (d[k] > dmax)
                        dmax = d[k];
                } else {
                    d[k] = 0.0f;
                }
            }
            if (sum <= 0.0f)
                continue;
            float out = SIM_FLOW_K * dmax;
            if (out >= hv)
                out = hv * (1.0f - SIM_DRAIN_KEEP);
            const float f = out / sum;
            float moved = 0.0f;
            float q;
            if (d[0] > 0.0f) {
                q = f * d[0]; moved += q;
                if (r > 0) hn[i - cols] += q; else edge_out += q;
            }
            if (d[1] > 0.0f) {
                q = f * d[1]; moved += q;
                if (r < rows - 1) hn[i + cols] += q; else edge_out += q;
            }
            if (d[2] > 0.0f) {
                q = f * d[2]; moved += q;
                if (c > 0) hn[i - 1] += q; else edge_out += q;
            }
            if (d[3] > 0.0f) {
                q = f * d[3]; moved += q;
                if (c < cols - 1) hn[i + 1] += q; else edge_out += q;
            }
            hn[i] -= moved;
        }
    }
    s->outflow_m3 += edge_out * s->cell_area_m2;

    /* 3. peak depth */
    float *peak = s->peak;
    for (size_t i = 0; i < n; i++)
        if (hn[i] > peak[i])
            peak[i] = hn[i];

    s->h = hn;
    s->hn = h;
    s->steps++;
}

int sim_step(SimState *s, int n_steps)
{
    for (int k = 0; k < n_steps && !s->done; k++) {
        step_once(s);
        if (s->steps >= s->total_steps)
            s->done = 1;
    }
    return s->done ? 0 : 1;
}

const float *sim_depth(const SimState *s)
{
    return s->h;
}

double sim_time_s(const SimState *s)
{
    return s->steps * SIM_DT_S;
}

int sim_raining(const SimState *s)
{
    return !s->done && s->steps * SIM_DT_S < s->dur_s;
}

SimStats sim_run_scenario(SimState *s, Scenario sc, float threshold_m,
                          int32_t *flood_count, float *max_depth)
{
    sim_begin(s, sc);
    while (sim_step(s, 256))
        ;

    const float *d = sim_depth(s);
    SimStats st;
    st.steps = s->steps;
    st.rain_m3 = s->rain_m3;
    st.outflow_m3 = s->outflow_m3;
    st.flooded_cells = 0;
    double stored = 0.0;
    for (size_t i = 0; i < s->n; i++) {
        stored += d[i];
        if (d[i] > threshold_m) {
            flood_count[i] += 1;
            st.flooded_cells++;
        }
        if (s->peak[i] > max_depth[i])
            max_depth[i] = s->peak[i];
    }
    st.stored_m3 = stored * s->cell_area_m2;
    return st;
}
