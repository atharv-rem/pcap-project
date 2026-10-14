# Bengaluru Flood-Risk Map using MPI

A C + MPI program that runs hundreds of rain scenarios (rain intensity x duration, e.g.
20 x 20 = 400 storms) on an SRTM elevation grid of Bengaluru (~30 m cells) with a
deliberately simple water-flow model. For every cell it counts in how many storms the cell
floods. The result is a flood-risk **screening** map, not a prediction.

Storms are independent, so whole storms are shared among MPI processes (dynamic
coordinator/worker mode, or a static block split for comparison). Per-cell results are
combined with `MPI_Reduce`.

## Layout

```
Makefile, mk/*.mk      build (each member owns one mk file)
data/raw/              SRTM tiles (put here by hand, not committed)
data/grid.bin/.meta    elevation grid made by scripts/prepare_map.py
src/sim.h              shared simulation API
src/sim.c, grid_io.c   water model and grid loader
src/main_serial.c      serial runner (baseline + reference answer)
src/mpi_main.c ...     MPI program
src/live.c             raylib live demo
scripts/               map preparation, benchmarks, plots, validation
tests/test_sim.c       model tests
docs/notes_M*.md       notes per team member
```

## Build and run (Linux, gcc, OpenMPI)

```sh
# 1. elevation grid: put SRTM 1" tiles (N12E077, N13E077 as .hgt or .tif) in data/raw/
python3 scripts/prepare_map.py --input data/raw/*.hgt --bbox 12.83 13.14 77.45 77.78 --out data/
#    or, without real data (fake terrain, clearly marked as synthetic):
python3 scripts/prepare_map.py --synthetic --out data/

# 2. build and test
make all          # build/flood_serial, build/flood_mpi, build/live
make test         # builds and runs build/test_sim

# 3. run
ARGS="--grid data/grid.bin --meta data/grid.meta --n-intensity 20 --n-duration 20 \
      --intensity-min 10 --intensity-max 100 --duration-min 1 --duration-max 6 --threshold 0.3"
build/flood_serial $ARGS --limit 12 --out results/serial
mpirun -np 4 build/flood_mpi $ARGS --limit 12 --mode dynamic --out results/dyn
cmp results/serial/freq.bin results/dyn/freq.bin     # must be identical
mpirun -np 12 build/flood_mpi $ARGS --mode dynamic --out results/full
python3 scripts/make_risk_map.py results/full
```

Outputs in `--out`: `freq.bin`, `maxdepth.bin` (float32 grids), `scenarios.csv`,
`timings.csv`, `run_info.csv`.
