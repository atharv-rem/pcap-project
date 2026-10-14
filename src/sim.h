#ifndef SIM_H
#define SIM_H
#include <stdint.h>

typedef struct {
    int rows, cols;
    float cell_size_m;      /* metres per cell side */
    float *height;          /* rows*cols, ground height in metres, row-major */
} Grid;

typedef struct {
    float intensity_mm_hr;  /* rain intensity, mm per hour */
    float duration_hr;      /* how long it rains, hours */
} Scenario;

typedef struct {
    int    steps;           /* time steps simulated */
    double rain_m3;         /* total rain added */
    double outflow_m3;      /* total water that left over the map edges */
    double stored_m3;       /* water on the map at the end */
    int    flooded_cells;   /* cells with depth > threshold at the end of the drain window */
} SimStats;

typedef struct SimState SimState;   /* opaque; owns the water-depth buffers */

int       grid_load(const char *bin_path, const char *meta_path, Grid *g); /* 0 = ok */
void      grid_free(Grid *g);
SimState *sim_create(const Grid *g);
void      sim_destroy(SimState *s);

/* Run ONE full storm: reset water, rain for the duration, then keep simulating for a fixed
   drain window of 240 steps after the rain stops (2 h at dt = 30 s), and stop. No convergence
   test and no step cap. Then, for every cell:
     - if its depth at that final step > threshold_m:  flood_count[i] += 1
     - max_depth[i] = max(max_depth[i], deepest water seen in that cell during this storm)
   flood_count and max_depth are rows*cols arrays owned by the caller and accumulated
   across storms. Must be deterministic (no threads, no randomness). */
SimStats  sim_run_scenario(SimState *s, Scenario sc, float threshold_m,
                           int32_t *flood_count, float *max_depth);

/* Step-by-step access, used by the live demo. sim_run_scenario must be built on these. */
void          sim_begin(SimState *s, Scenario sc);   /* reset water, start a storm */
int           sim_step(SimState *s, int n_steps);    /* advance n steps; 1 = still running, 0 = finished */
const float  *sim_depth(const SimState *s);          /* rows*cols water depth in metres */
double        sim_time_s(const SimState *s);         /* simulated seconds so far */
int           sim_raining(const SimState *s);        /* 1 while rain is still falling */
#endif
