# Notes M2: the MPI engine

## Done
- `src/scenarios.h/.c`: scenario list (contract C3). Values `(float)(min + (max-min)*i/(n-1))`
  computed in double then cast, one value = min, `id = i_intensity * n_duration + i_duration`,
  `--limit` honoured. Every rank builds the list itself; only ids travel over MPI.
  `make scenarios_check` builds `build/scenarios_check` (no MPI), which prints the first
  scenarios in the `scenarios.csv` format plus the exact float bits (`%a`).
- `mk/mpi.mk`: `make mpi` -> `build/flood_mpi` (`mpicc -O2 -std=c11 -Wall -Wextra ... -lm`),
  appended to `all`.
- `src/mpi_main.c` -> `build/flood_mpi`: same flags and defaults as `flood_serial`, np=1 /
  dynamic / static modes, MPI_Reduce SUM + MAX, MPI_Gather of busy times, the five C4 files.
- `scripts/run_benchmarks.sh`: the benchmark sweep.

## Program flow (`src/mpi_main.c`)
1. `MPI_Init`, `MPI_Comm_rank`, `MPI_Comm_size`.
2. Rank 0 parses the command line (bad flag / bad value / unknown mode -> message + usage) and
   creates `--out`. Settings go to all ranks with three `MPI_Bcast`s: `int iv[5]`
   (n_int, n_dur, limit, mode, ok), `double dv[5]` (int_min, int_max, dur_min, dur_max,
   threshold), `char path[3][512]` (grid, meta, out). If `ok == 0` every rank calls `MPI_Abort`.
3. Every rank builds the scenario list, loads the grid (`grid_load`; failure -> `MPI_Abort`),
   creates its own `SimState`, and allocates zeroed `flood_count` / `max_depth` (rank 0 too).
4. `MPI_Barrier`, start `MPI_Wtime`, run (below), `MPI_Barrier`, stop: that is `wall_time_s`.
5. `MPI_Reduce(MPI_IN_PLACE at root, flood_count, MPI_INT32_T, MPI_SUM)` and
   `MPI_Reduce(..., max_depth, MPI_FLOAT, MPI_MAX)`. Element count = rows*cols (checked
   <= INT_MAX; 1.33 M for the 30 m grid).
6. `MPI_Gather` of `{scenarios_run, busy_s}` (2 doubles per rank).
7. Rank 0 writes `freq.bin` (= `(float)count / (float)n_run`, same expression as
   `main_serial.c`), `maxdepth.bin`, `scenarios.csv` (sorted by id, `rank` = the worker that
   ran it), `timings.csv` (one row per rank, rank 0 has 0 / 0.0 when np > 1), `run_info.csv`
   (`mode` = dynamic or static as given). Formats are copied from `main_serial.c`.
   It prints a summary: mode, np, wall time, combine time, per-rank busy/count, imbalance.

Run modes:
- **np = 1**: rank 0 simulates everything (the baseline; folder `np1_dynamic_rep{R}`).
- **dynamic** (np >= 2): rank 0 = coordinator, never simulates.
- **static** (np >= 2): worker w (1..np-1) runs ids `[start, start+count)` with
  `base = n / W`, `rem = n % W`, `k = w-1`, `count = base + (k < rem)`,
  `start = k*base + min(k, rem)` (sizes differ by at most one). Rank 0 runs nothing. At the end
  `MPI_Gatherv` collects the records; rank 0 computes counts/displacements itself, and since the
  blocks are contiguous and in rank order the records arrive sorted by id.

Load imbalance = max busy / mean busy over the simulating ranks (1..np-1, or rank 0 if np=1).

## Message layout (dynamic mode)
| tag | direction | payload |
|---|---|---|
| `TAG_READY = 1` | worker -> rank 0 | `double rec[6]` (result record, below). First READY has `id = -1`. |
| `TAG_WORK = 2` | rank 0 -> worker | `int id`: next scenario, or `-1` = stop |

Result record (`REC_LEN = 6` doubles, also used by the static `MPI_Gatherv`):

| index | field |
|---|---|
| 0 `REC_ID` | scenario id (-1 = no result yet) |
| 1 `REC_RANK` | rank that ran it |
| 2 `REC_FLOODED` | `SimStats.flooded_cells` |
| 3 `REC_RUNTIME` | seconds inside `sim_run_scenario` (`MPI_Wtime`) |
| 4 `REC_STEPS` | `SimStats.steps` |
| 5 `REC_MASS_ERR` | `|rain - outflow - stored| / rain` |

Coordinator: `MPI_Recv(ANY_SOURCE, TAG_READY)` -> store record if id >= 0 -> `MPI_Send` next
id (or -1, and one fewer active worker) to `status.MPI_SOURCE`; ends when every worker has
been sent -1. Worker: send READY, `MPI_Recv` id from 0, stop on -1, else run and repeat.
Fewer scenarios than workers: the extra workers get -1 on their first READY (no deadlock).

## How to run
```
make mpi
mpirun -np 4 build/flood_mpi --grid data_ds3/grid.bin --meta data_ds3/grid.meta \
  --n-intensity 4 --n-duration 3 --intensity-min 10 --intensity-max 60 \
  --duration-min 1 --duration-max 4 --threshold 0.3 --mode dynamic --limit 12 --out results/dyn
# same with --mode static; -np 1 is the serial baseline
scripts/run_benchmarks.sh --grid data_ds3/grid.bin --meta data_ds3/grid.meta --reps 3 \
  --nps "1 2 4 6 8 10 12 14" --extra "--n-intensity 20 --n-duration 20 --intensity-min 10 \
  --intensity-max 60 --duration-min 1 --duration-max 4 --threshold 0.3"
```
In WSL as root, `mpirun` needs `--allow-run-as-root` (the benchmark script adds it itself, and
adds `--oversubscribe` only when np > `nproc`). Benchmark options: `--grid --meta --limit
--reps --nps --extra --pause` (seconds between runs, default 5) `--out` (default
`results/bench`). Runs go to `results/bench/np{N}_{mode}_rep{R}/`, stdout to
`results/bench/np{N}_{mode}_rep{R}.log`, `lscpu` to `results/bench/machine.txt`.

## Checks: status
Pushed before the toolchain was available, so **nothing below has been run with real MPI yet**.
- Done: `src/mpi_main.c` + `src/scenarios.c` compile with zero warnings (`gcc -O2 -std=c11
  -Wall -Wextra -fsyntax-only`) against a stub `mpi.h` (WSL had no gcc/make/Open MPI).
- Done: `scenarios_check 4 3 10 60 1 4 12` prints ids 0..11 = intensities 10, 26.6667,
  43.3333, 60 x durations 1, 2.5, 4 (same formula as `main_serial.c`).
- **Not tested**: `make mpi` with real `mpicc`; Task 5 checks (cmp of serial vs np 2/4 in both
  modes, imbalance static vs dynamic, np > scenarios, 30 m `--limit 8` np 4 run);
  `scripts/run_benchmarks.sh`. `data_ds3/` was not available yet.
