/* scenarios.h - [M2] the list of rain scenarios (contract C3).
 *
 * Every MPI rank builds this list itself from the broadcast settings, so the list never has
 * to be sent: a scenario is identified everywhere by its integer id alone.
 *
 *   intensity values: n_int values evenly spaced in [int_min, int_max], both ends included
 *   duration  values: n_dur values evenly spaced in [dur_min, dur_max], both ends included
 *   (a single value = the minimum)
 *   id = i_intensity * n_dur + i_duration
 *   --limit K > 0 keeps only ids 0..K-1.
 *
 * The values are computed in double and then cast to float, exactly as docs/notes_M1.md and
 * main_serial.c do, so flood_mpi and flood_serial simulate bit-identical storms. */
#ifndef SCENARIOS_H
#define SCENARIOS_H
#include "sim.h"

typedef struct {
    int    n_int, n_dur;        /* --n-intensity, --n-duration */
    double int_min, int_max;    /* --intensity-min/max, mm/hr */
    double dur_min, dur_max;    /* --duration-min/max, hours */
    int    limit;               /* --limit, 0 = all */
} ScenarioSpec;

typedef struct {
    int       n;                /* number of scenarios that will run (after --limit) */
    int       total;            /* n_int * n_dur */
    Scenario *sc;               /* sc[id], id = 0..n-1 */
} ScenarioList;

/* One evenly spaced value: (float)(lo + (hi - lo) * i / (n - 1)) in double; n == 1 -> lo. */
float scenario_value(double lo, double hi, int n, int i);

/* Build the list. Returns 0 on success, -1 on bad settings or out of memory. */
int  scenarios_build(const ScenarioSpec *spec, ScenarioList *list);
void scenarios_free(ScenarioList *list);
#endif
