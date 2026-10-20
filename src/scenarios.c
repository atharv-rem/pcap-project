/* scenarios.c - [M2] scenario list builder, see scenarios.h for the rules (contract C3). */
#include "scenarios.h"

#include <stdio.h>
#include <stdlib.h>

float scenario_value(double lo, double hi, int n, int i)
{
    if (n == 1)
        return (float)lo;
    /* same expression as main_serial.c: computed in double, converted to float once */
    return (float)(lo + (hi - lo) * i / (n - 1));
}

int scenarios_build(const ScenarioSpec *spec, ScenarioList *list)
{
    list->n = 0;
    list->total = 0;
    list->sc = NULL;
    if (spec->n_int < 1 || spec->n_dur < 1 || spec->limit < 0)
        return -1;
    if (spec->n_int > 100000 / spec->n_dur)     /* keeps ids and counts far below INT_MAX */
        return -1;

    list->total = spec->n_int * spec->n_dur;
    list->n = (spec->limit > 0 && spec->limit < list->total) ? spec->limit : list->total;
    list->sc = malloc((size_t)list->n * sizeof *list->sc);
    if (!list->sc)
        return -1;

    for (int id = 0; id < list->n; id++) {
        int ii = id / spec->n_dur;              /* id = i_intensity * n_dur + i_duration */
        int id_ = id % spec->n_dur;
        list->sc[id].intensity_mm_hr = scenario_value(spec->int_min, spec->int_max, spec->n_int, ii);
        list->sc[id].duration_hr = scenario_value(spec->dur_min, spec->dur_max, spec->n_dur, id_);
    }
    return 0;
}

void scenarios_free(ScenarioList *list)
{
    free(list->sc);
    list->sc = NULL;
    list->n = 0;
}

#ifdef SCENARIOS_CHECK_MAIN
/* Tiny self-check (build/scenarios_check, `make scenarios_check`): prints the first scenarios
 * in the same "%.6g" format as scenarios.csv, plus the exact float bits in hex, so the list can
 * be compared with the intensity/duration columns written by build/flood_serial.
 * usage: scenarios_check n_int n_dur int_min int_max dur_min dur_max [limit] */
int main(int argc, char **argv)
{
    if (argc < 7) {
        fprintf(stderr, "usage: %s n_int n_dur int_min int_max dur_min dur_max [limit]\n", argv[0]);
        return 2;
    }
    ScenarioSpec sp = {atoi(argv[1]), atoi(argv[2]), atof(argv[3]), atof(argv[4]),
                       atof(argv[5]), atof(argv[6]), argc > 7 ? atoi(argv[7]) : 12};
    ScenarioList L;
    if (scenarios_build(&sp, &L) != 0) {
        fprintf(stderr, "bad settings\n");
        return 1;
    }
    printf("id,intensity_mm_hr,duration_hr,intensity_hex,duration_hex\n");
    for (int id = 0; id < L.n; id++)
        printf("%d,%.6g,%.6g,%a,%a\n", id, L.sc[id].intensity_mm_hr, L.sc[id].duration_hr,
               (double)L.sc[id].intensity_mm_hr, (double)L.sc[id].duration_hr);
    scenarios_free(&L);
    return 0;
}
#endif
