/* grid_io.c - load the elevation grid described in contract C1. */
#include "sim.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int host_is_little_endian(void)
{
    const uint16_t one = 1;
    return *(const unsigned char *)&one == 1;
}

int grid_load(const char *bin_path, const char *meta_path, Grid *g)
{
    memset(g, 0, sizeof *g);

    FILE *fm = fopen(meta_path, "r");
    if (!fm) {
        fprintf(stderr, "grid_load: cannot open %s\n", meta_path);
        return -1;
    }
    char line[256];
    int rows = -1, cols = -1;
    double cell = -1.0;
    while (fgets(line, sizeof line, fm)) {
        char key[64];
        char val[128];
        if (sscanf(line, " %63[^= ] = %127s", key, val) != 2)
            continue;
        if (strcmp(key, "rows") == 0)
            rows = atoi(val);
        else if (strcmp(key, "cols") == 0)
            cols = atoi(val);
        else if (strcmp(key, "cell_size_m") == 0)
            cell = atof(val);
    }
    fclose(fm);
    if (rows <= 0 || cols <= 0 || cell <= 0.0) {
        fprintf(stderr, "grid_load: %s must define rows, cols and cell_size_m\n", meta_path);
        return -1;
    }

    size_t n = (size_t)rows * (size_t)cols;
    float *h = malloc(n * sizeof *h);
    if (!h) {
        fprintf(stderr, "grid_load: out of memory (%d x %d)\n", rows, cols);
        return -1;
    }
    FILE *fb = fopen(bin_path, "rb");
    if (!fb) {
        fprintf(stderr, "grid_load: cannot open %s\n", bin_path);
        free(h);
        return -1;
    }
    size_t got = fread(h, sizeof *h, n, fb);
    int extra = fgetc(fb) != EOF;
    fclose(fb);
    if (got != n || extra) {
        fprintf(stderr, "grid_load: %s does not hold exactly rows*cols = %zu float32 values\n",
                bin_path, n);
        free(h);
        return -1;
    }

    if (!host_is_little_endian()) {
        for (size_t i = 0; i < n; i++) {
            unsigned char *b = (unsigned char *)&h[i];
            unsigned char t0 = b[0], t1 = b[1];
            b[0] = b[3]; b[1] = b[2]; b[2] = t1; b[3] = t0;
        }
    }
    for (size_t i = 0; i < n; i++) {
        if (!isfinite(h[i])) {
            fprintf(stderr, "grid_load: non-finite height at cell %zu\n", i);
            free(h);
            return -1;
        }
    }

    g->rows = rows;
    g->cols = cols;
    g->cell_size_m = (float)cell;
    g->height = h;
    return 0;
}

void grid_free(Grid *g)
{
    if (!g)
        return;
    free(g->height);
    g->height = NULL;
    g->rows = g->cols = 0;
}
