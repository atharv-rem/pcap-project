# Notes M1: data preparation, simulation core, serial runner

## Done
- Skeleton: folders, `.gitignore`, top-level `Makefile`, `mk/serial.mk`, `README.md`, `AGENTS.md`.
- `src/sim.h`: exact contract C2 text.
- `scripts/prepare_map.py`: SRTM `.hgt` / GeoTIFF (rasterio if installed, else Pillow + GeoTIFF
  tags) -> merge, crop to bbox, fill voids (nearest, scipy; numpy fallback), 3x3 box smoothing
  (on by default, `--no-smooth` to skip), `--downsample N` (N x N block average), writes `data/grid.bin` + `data/grid.meta` (C1).
  `--synthetic` makes fake terrain (hills, valley, 8 bowls, 0.03 m noise) and says so loudly;
  `source=` in grid.meta says SYNTHETIC.
- `src/grid_io.c`, `src/sim.c`: water model (constants documented at the top of `sim.c`).
- `src/main_serial.c` -> `build/flood_serial`: command line C3, five output files C4.
- `tests/test_sim.c` -> `build/test_sim`: flat plane, bowl, mass conservation, determinism,
  timing (`--no-timing` skips the slow part).

## Model in one paragraph
dt = 30 s. Rain is added to every cell while it rains. Each wet cell moves
`min(depth, 0.25 * largest surface drop)` to its lower 4-neighbours in proportion to the
drops (two buffers, so cell order does not matter). Map-edge cells drain over the edge
(outflow). Each storm runs a **fixed number of steps**: `ceil(duration / 30 s) + POST_RAIN_STEPS (240)`
(rain + 2 simulated hours of draining), so 360..960 steps. Waiting for the water to stop
moving was tried first, but full ponds spill so slowly that a storm took 12,000-50,000 steps.
Flood = depth > threshold at the final step.

## Scenario list (M2: please match this exactly)
`value_i = (float)(min + (max - min) * i / (n - 1))` computed in **double**, then cast to
float; one value -> `min`. `id = i_intensity * n_duration + i_duration`. If M2 computes the
values differently (e.g. in float), last-bit differences can break the `cmp` check.

## How to run
```
python3 scripts/prepare_map.py --input data/raw/*.hgt --out data/   # or --synthetic
make serial test
build/flood_serial --grid data/grid.bin --meta data/grid.meta --n-intensity 20 --n-duration 20 \
  --intensity-min 10 --intensity-max 100 --duration-min 1 --duration-max 6 --threshold 0.3 \
  --limit 4 --out results/serial4
```

## Measured (WSL Ubuntu, gcc 13.3 -O2, one core)
**Real SRTM grid, 30 m cells, 1116 x 1188** (`test_sim` timing):

| storm | steps | time |
|---|---|---|
| 10 mm/h x 1 h | 360 | 4.1 s |
| 55 mm/h x 3.5 h | 660 | 13.0 s |
| 100 mm/h x 6 h | 960 | 21.4 s |

That is about 13 s per storm on average, so 400 storms take about 85-90 min on one process.
**`--downsample 3` (90 m cells, 372 x 396):** a 1 h storm takes 0.47 s and a 6 h storm 1.93 s.
`flood_serial --limit 4` on the real grid took 31 s; two of the four storms were 2x slower
than expected (other load on the laptop), so timings vary by up to about 2x between runs.
Mass error is 1e-7 to 3e-6. Time per storm grows with duration (more steps) and with how wet
the map is, which gives the load imbalance the dynamic mode is meant to handle.

## Not tested / caveats
- Real SRTM data: `N12E077.hgt` + `N13E077.hgt` in `data/raw/` give a 1116 x 1188 grid,
  heights 729-971 m (mean 885 m), 0 voids. `--downsample 3` (3x3 block average, 90 m
  cells) gives 372 x 396. `.hgt.gz` input gives a byte-identical grid. GeoTIFF was only
  tested with fake tiles.
- **`make` itself was not run.** This machine has no `make` or `mpicc`, so I built with the
  same gcc commands the `mk/serial.mk` rules use.
- `cell_size_m=30.0` as in the contract example (a real 1" cell is ~30.9 m N-S, ~30.1 m E-W).
- The grid is snapped to the SRTM pixel lattice, so `lat_top` / `lon_left` differ from the
  bbox by up to half a cell (e.g. 13.140139).
- The heavy synthetic storm floods ~36% of the map: the synthetic terrain has many closed
  bowls and only 2 h of draining. The results on real terrain will look different.
