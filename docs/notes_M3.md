# Notes M3: results, validation and the live demo

## Done
- `data/known_spots.csv`: the team's 5 seed spots, exactly as given. **Coordinates are
  approximate (from the team, not surveyed) and all `verified=no`.** The team must check each
  point on a map, add rows and set `verified=yes` themselves.
- `scripts/rank_areas.py`: blocks of ~`--block-m` m, mean frequency + deepest water,
  `ranked_areas.csv`, top-N table. Also holds the shared helpers (meta reading, grid-size
  checks, spot loading) that `validate.py` and `make_risk_map.py` import.
- `scripts/validate.py`: rank/percentile/top-10% per known spot, `validation.csv`. The
  headline counts only `verified=yes` spots (says so if there are none); misses are listed
  with their rank.
- `scripts/make_risk_map.py`: `risk_map.png` (200 dpi, A4-sized), hillshade, lat/lon axes,
  never-flooded cells transparent, labelled known spots (labels move to avoid overlaps).
- `scripts/flooded_area_table.py`: `flooded_area_table.csv` + `.png` (intensity x duration).
- `scripts/make_fake_bench.py`: FAKE benchmark tree for chart development (toy cost model).
- `scripts/plot_timings.py`: `figures/speedup.png`, `imbalance.png`, `busy_per_rank.png`.
- `src/live.c` + `mk/live.mk`: raylib replay of one storm (`make live` -> `build/live`).

All scripts: Python 3.9+, NumPy + Matplotlib only. Every script that takes `--meta`
**stops with a clear message** if `freq.bin` / `maxdepth.bin` / `--grid` / `run_info.csv`
do not match the meta file's rows x cols. Spots with a blank or non-numeric lat/lon, or
outside the grid, are skipped with a printed message; any number of rows works.

## How to run
The defaults are the 30 m grid (`data/grid.*`). For results made on the 90 m grid pass
`--grid data_ds3/grid.bin --meta data_ds3/grid.meta`.
```
# dev data (90 m grid, 64 storms, ~105 s)
build/flood_serial --grid data_ds3/grid.bin --meta data_ds3/grid.meta --n-intensity 8 \
  --n-duration 8 --intensity-min 10 --intensity-max 60 --duration-min 1 --duration-max 4 \
  --threshold 0.3 --out results/dev
python3 scripts/make_risk_map.py results/dev --grid data_ds3/grid.bin --meta data_ds3/grid.meta
python3 scripts/rank_areas.py results/dev --meta data_ds3/grid.meta [--block-m 500] [--top 20]
python3 scripts/validate.py results/dev --meta data_ds3/grid.meta [--block-m 500]
python3 scripts/flooded_area_table.py results/dev

# final results (30 m grid, defaults)
python3 scripts/make_risk_map.py results/full
python3 scripts/rank_areas.py results/full
python3 scripts/validate.py results/full
python3 scripts/flooded_area_table.py results/full

# timing charts
python3 scripts/make_fake_bench.py --out results_fake/bench     # FAKE, testing only
python3 scripts/plot_timings.py results_fake/bench
python3 scripts/plot_timings.py results/bench [--busy-np 8]    # Member 2's real runs

# live demo (needs raylib and a display / WSLg). Ubuntu 24.04 has NO libraylib-dev package,
# so build raylib once from source (outside the repo, never vendored):
sudo apt install -y build-essential git cmake pkg-config libx11-dev libxrandr-dev \
  libxinerama-dev libxcursor-dev libxi-dev libgl1-mesa-dev libglu1-mesa-dev
git clone --depth 1 --branch 5.5 https://github.com/raysan5/raylib.git ~/src/raylib
cd ~/src/raylib && cmake -B build -DCMAKE_BUILD_TYPE=Release -DBUILD_EXAMPLES=OFF \
  -DGLFW_BUILD_WAYLAND=OFF && cmake --build build -j && sudo cmake --install build
cd -    # back to the repo
make live
build/live --grid data_ds3/grid.bin --meta data_ds3/grid.meta --intensity 40 --duration 2.5 \
  [--threshold 0.3] [--steps-per-frame 2] [--spots data/known_spots.csv]
```
Live keys: SPACE pause/resume, UP/DOWN steps per frame (1..50), R restart, P hide/show
place names, H hide/show the controls card, ESC quit.
Place names come from `data/places.csv` (`name,lat,lon`, 27 localities, `--places` to
change). **This file is only for orientation labels in the live demo and is not used by
validate.py.** Its coordinates are approximate (written from general knowledge, not
surveyed or looked up); the team should check them on a map. A place label is hidden where
it would overlap a flood-spot label, another place label or a card; zoom in to see more. Text uses DejaVu Sans (then Ubuntu, Liberation Sans, then raylib's
built-in font); `--font /path/to/font.ttf` picks another. Cards: storm status with a
rain -> drain progress bar and flooded area (top left), controls (top right), cell under
the mouse (bottom left), legend (bottom right).
Mouse: wheel zooms around the cursor (up to 40x), drag moves the map, F fits it again;
pointing at a cell shows its lat/lon, ground height, water depth and FLOODED if > threshold.
For more detail when zoomed in, use the 30 m grid (`--grid data/grid.bin --meta
data/grid.meta --steps-per-frame 1`); a step is ~25 ms there, so it runs slower.

## Final results (21 Oct 2026, this laptop)
**Correctness:** `flood_mpi` dynamic and static on np 2 and 4 (30 m grid, 12 storms) give
`freq.bin` and `maxdepth.bin` byte-identical to `flood_serial` (`cmp`), and identical
`scenarios.csv` apart from runtime/rank.

**Full run, SRTM 30 m, 400 storms, np 12 dynamic:** 913 s wall (`results/full/`).
Validation (lakes excluded): 75 of 384 verified BBMP points in the top 10% of 4,549 blocks
= 20%, **2.0x better than chance** (flood-prone 16%, low-lying 20%, vulnerable 20%).

**Benchmark** (`results/bench/`, 90 m grid, 400 storms, 3 reps, median wall time;
`mpirun --use-hwthread-cpus`):

| np | dynamic (s) | static (s) | speed-up dyn / stat | imbalance dyn / stat |
|---|---|---|---|---|
| 1 | 402 | - | 1.0 | 1.00 |
| 2 | 468 | 485 | 0.86 / 0.83 | 1.00 / 1.00 |
| 4 | 246 | 253 | 1.6 / 1.6 | 1.00 / 1.04 |
| 8 | 170 | 178 | 2.4 / 2.3 | 1.01 / 1.05 |
| 14 | 131 | 138 | **3.1 / 2.9** | **1.02 / 1.10** |

- Dynamic is faster than static at every np >= 4 and keeps imbalance <= 1.02; static
  reaches 1.10. The gap is modest because ids run duration-fastest, so every contiguous
  static block already mixes short and long storms.
- **Why only 3.1x:** the total busy time grows with np: the average storm takes 1.0 s
  alone, 1.8 s with 3 workers, 2.9 s with 7, 4.1 s with 13 (`figures/per_storm.png`).
  The MPI part costs almost nothing (balance is near perfect, messages are a few bytes);
  the storms themselves run slower when many run at once: shared L3 cache and memory
  bandwidth (each process streams ~2.4 MB of arrays per step), the hybrid CPU (4 P-cores
  plus slower E-cores; WSL exposes 9 cores / 18 threads), hyperthreads sharing a core
  above 9 processes, and lower all-core clock speed. np=2 is slower than np=1 because the
  coordinator busy-polls in `MPI_Recv` and competes with the single worker.
- Timing noise: one np=1 repetition took 566 s against 390/402 (medians are used).

## Known flood points and lakes (added after the team left; the human asked for web data)
- **`data/known_spots.csv` now holds 391 spots:** the team's 5 seeds (verified=no; checked
  against OpenStreetMap/Nominatim, each within ~100-650 m) plus **386 official BBMP points**
  (verified=yes, source_url = the exact resource). Source: OpenCity dataset "Flooding
  Locations in Bengaluru Urban" (publisher BBMP, source KSRSAC),
  https://data.opencity.in/dataset/flooding-locations-in-bengaluru-urban : 200 flood-
  vulnerable locations, 70 flood-prone locations, 129 low-lying areas; 12 duplicates
  (< 50 m) merged, 1 point without coordinates skipped. Rebuild with
  `python3 scripts/import_bbmp_spots.py` (KML files in `data/raw/`, gitignored).
- **Lakes:** `data/raw/lakes_osm.json` from the OpenStreetMap Overpass API
  (natural=water, landuse=reservoir in the grid bbox; 1,924 polygons). 
  `python3 scripts/lake_mask.py --meta data/grid.meta` (and `--meta data_ds3/grid.meta`)
  writes `lakes_mask.bin` (uint8, 1 = lake) next to the meta file: ~40 km2, 3.4% of the map.
  `make_risk_map.py` draws lakes in slate grey; `rank_areas.py` / `validate.py` ignore lake
  cells and drop blocks that are > 50% lake. All three find the mask automatically;
  `--lakes none` turns it off.
- Overpass query used (needs a User-Agent header, curl's default gets HTTP 406):
  `[out:json][timeout:120];(way["natural"="water"](12.830,77.449,13.141,77.780);relation["natural"="water"](12.830,77.449,13.141,77.780);way["landuse"="reservoir"](12.830,77.449,13.141,77.780););out geom;`
- **Validation on the 90 m dev run (64 storms), lakes excluded:** 87 of 383 verified BBMP
  points are in the top 10% of blocks = 23%, against 10% for random points -> **2.3x better
  than chance** (vulnerable 25%, low-lying 24%, flood-prone 13%). Without the lake mask it
  was 2.0x. 3 points fall in lake blocks and are not ranked.
- With > 15 spots the risk map draws small unlabelled dots; with > 20 the live demo draws
  dots and names the nearest one in the cursor card. The 5 seed names are also in
  `data/places.csv` so they keep a label in the live demo.

## Better terrain: FABDEM
- FABDEM V1-2 (Hawker et al., University of Bristol; Copernicus GLO-30 with buildings and
  trees removed; licence CC BY-NC-SA 4.0). Tiles `N12E077_FABDEM_V1-2.tif`,
  `N13E077_FABDEM_V1-2.tif` from the Hugging Face mirror `pavelzaitsau/fabdem-v12`
  (the official Bristol download only offers 10 x 10 degree zips), in `data/raw/fabdem/`.
- `python3 scripts/prepare_map.py --input data/raw/fabdem/*.tif --out data_fabdem/` (and
  `--downsample 3 --out data_fabdem_ds3/`). `prepare_map.py` now writes the right `source=`
  for FABDEM input. Same lattice, size and corner as the SRTM grid (1116 x 1188), so results
  can be compared cell by cell. Lake masks: `lake_mask.py --meta data_fabdem/grid.meta` etc.
- SRTM is on average 3.0 m higher (median 2.9 m, 95th percentile 7.1 m); 18% of cells lose
  more than 5 m of rooftops/trees in FABDEM.
- Full run: `results/full_fabdem/` (same 400 storms as `results/full/`), 872 s wall on
  np 12. The SRTM grid in `data/` is unchanged; the benchmark uses `data_ds3/` (SRTM 90 m),
  since timing does not depend on which terrain is used.
- **FABDEM vs SRTM** (384 verified BBMP points, lakes excluded):

  | metric | random | SRTM | FABDEM |
  |---|---|---|---|
  | in riskiest 10% / 20% / 30% of blocks | 10 / 20 / 30% | 20 / 39 / 54% | 20 / 40 / 55% |
  | mean percentile | 50 | 63.5 | **66.2** |
  | in the safer half (misses) | 50% | 31% | **26%** |

  Same headline (2.0x at the top 10%), slightly better everywhere else. Visually much
  better: SRTM's map is speckled with single-cell "ponds" (rooftops and trees acting as
  dams), FABDEM's shows continuous flood channels along the valleys and lake chains.
  **Use `results/full_fabdem/` as the main map in the report**; SRTM is the comparison.
- Live demo on FABDEM: `build/live --grid data_fabdem_ds3/grid.bin --meta
  data_fabdem_ds3/grid.meta --intensity 40 --duration 2.5`.

## Accuracy improvements (drains, soak-in, calibration)
- **Drains:** `data/raw/waterways_osm.json` (Overpass: `way["waterway"~"^(drain|canal|stream|river|ditch)$"]`
  in the grid bbox; 2,830 ways, ~990 km: 708 km drains, 148 km streams, 108 km rivers,
  27 km ditches, culverts included). `scripts/burn_drains.py` lowers every cell crossed by
  a waterway by `--depth` m (traced 4-connected, since water only moves N/S/E/W) and writes
  a new grid folder: `data_fabdem_drains/` (30 m, 2.9% of cells) and
  `data_fabdem_drains_ds3/` (90 m, 8.5%), each with `drains_mask.bin` and `lakes_mask.bin`.
- **Soak-in:** new optional flag `--loss L` (mm/h) in `flood_serial` and `flood_mpi`
  (default 0 = old behaviour): the model gets `max(0, intensity - L)` ("phi index");
  `scenarios.csv` keeps the real intensity. Checked: serial == MPI dynamic == MPI static
  (`cmp`, np 4) for loss 0 and 15.
- **Fair scoring:** `scripts/compare_runs.py` scores runs by AUC (chance a BBMP point scores
  higher than a random land point; 0.5 = guessing) and top-10% hit rate (10% = guessing,
  ties at the cut-off get proportional credit), using the highest flood frequency within
  0 / 150 / 300 m of each point, and the same for 20,000 random land points. Spots are split
  into half A (choose settings) and half B (report).
- **Calibration** (`exp/`, 90 m FABDEM, 400 storms, np 14, ~73 s per run): drains
  0/2/4 m x loss 0/10/20 mm/h. Best on A at 150 m: drains 2 m, loss 0 (AUC A 0.623 vs 0.589
  without drains; half B 0.645 vs 0.603). Soak-in did not improve the ranking (it only
  shrinks the flooded area), so the final run uses loss 0.
- **Final 30 m comparison** (half B, never used for choices):

  | map | AUC cell | AUC 150 m | AUC 300 m | top-10% (cell) |
  |---|---|---|---|---|
  | SRTM | 0.580 | 0.583 | 0.549 | 24% |
  | FABDEM | 0.623 | 0.668 | 0.680 | 30% |
  | **FABDEM + drains** (`results/full_fabdem_drains/`, 863 s) | **0.625** | **0.684** | **0.708** | **31%** |

  The old block headline is 1.9x (73 of 384) for FABDEM + drains vs 2.0x for the others;
  the neighbourhood AUC is the fairer measure. **Main map for the report:
  `results/full_fabdem_drains/`.** Live demo: `build/live --grid
  data_fabdem_drains_ds3/grid.bin --meta data_fabdem_drains_ds3/grid.meta ...`.

## Peak depth as the risk score
- The default score counts a cell as flooded only if water is still > 0.3 m deep at the
  end of the 2 h drain window. Scoring by **peak depth** (deepest water the cell reached in
  any storm, `maxdepth.bin`, already written by every run) matches the BBMP points better:
  90 m, drains, 150 m radius: AUC A 0.623 -> 0.680, B 0.645 -> 0.683. On the 30 m final run
  (half B): 0.684 -> 0.685 at 150 m, 0.708 -> 0.712 at 300 m. A wider storm range
  (10-100 mm/h, 1-6 h) added nothing beyond noise (A 0.684 vs 0.680), so the standard
  range is kept. Tuning has levelled off around AUC 0.68-0.71.
- New options: `make_risk_map.py --field maxdepth` -> `peak_depth_map.png` (colour 0-2 m,
  cells < 0.1 m transparent); `rank_areas.py --by peak` -> `ranked_areas_peak.csv` (extra
  column mean_peak_depth_m); `validate.py --by peak` -> `validation_peak.csv`;
  `compare_runs.py --field maxdepth.bin`.
- **Final result (`results/full_fabdem_drains/`, peak depth):** 87 of 384 verified BBMP
  points in the top 10% of blocks = **2.3x better than chance** (vulnerable 25%, low-lying
  22%, flood-prone 17%); 6 of the 10 top-ranked blocks have a BBMP point within 1 km.
  Caveat: a few closed hollows reach unrealistic peak depths (up to 11 m), hence the 2 m
  colour cap; depths are model values, not predictions.
- A repeat benchmark on 21 Oct 10:00 was stopped because the laptop was on battery (16%,
  Windows "discharging"): np=1 took 1,237 s against 402 s in the overnight benchmark. The
  overnight benchmark ran on mains power and is the official result (`results/bench/`).
  Timings on this laptop vary a lot with power state and background load (the morning
  calibration runs took 73 s for 400 storms at np 14, the overnight median was 131 s), so
  only compare timings taken in the same session.
- Re-check on mains power, 21 Oct 12:30-13:07, 1 repetition (`results/bench_plugged/`):
  np 1 458 s; np 4 343 / 288 s; np 8 180 / 180 s; np 14 162 / 149 s (dynamic / static) =
  2.8x / 3.1x; imbalance at np 14 1.02 / 1.08. Confirms ~3x and the better balance of
  dynamic mode, but static was sometimes faster in wall time: run-to-run noise (10-20%) is
  larger than the ~5% dynamic-static gap, so the imbalance figures are the clearer evidence.

## OpenStreetMap background
- `python3 scripts/osm_basemap.py --meta data_fabdem/grid.meta` downloads the 64 standard
  OSM tiles (zoom 13) covering the grid once (cached in `data/raw/osm/tiles/`, gitignored),
  reprojects them to the grid's lat/lon lattice and writes `data/raw/osm/basemap.png`
  (original colours), `basemap_muted.png` (mostly grey, so OSM's blue water and green parks
  do not clash with the flood colours) and `basemap.txt` (the area covered). All our grids
  (SRTM/FABDEM, 30 m/90 m) cover the same area, so one basemap serves all of them.
  Please keep the zoom at 13: the OSM tile policy forbids bulk downloads.
- `make_risk_map.py --basemap auto|osm|hillshade|none` (auto = OSM if the basemap exists,
  else hillshade). Credit "(c) OpenStreetMap contributors" is printed in the footer.
- `build/live` draws the water over the street map when the basemap exists (`--basemap
  PATH|none`); **B** switches street map / terrain; place labels start hidden (P shows them)
  because the street map already names places. Credit shown in the legend.

## Design choices
- **Blocks:** side = `round(block_m / cell_size_m)` cells (90 m: 6 cells = 540 m; 30 m: 17
  cells = 510 m). Blocks on the right/bottom edge can be smaller. Ranking order: mean
  frequency, then max depth, both descending; `validate.py` uses the same order.
  Percentile = share of blocks ranked below; top 10% = rank <= ceil(0.1 x blocks).
- **Risk-map colours:** light blue -> blue -> orange -> dark red, with lightness falling all
  the way, so it reads as one ordered scale (blue = calm, red = strong, as asked).
- **Timing charts:** median wall time over the reps; the faint dots are the single reps.
  Ideal line = np-1 workers (1 at np=1). Imbalance = max / mean busy over ranks 1..np-1.
  `busy_per_rank.png` uses the rep with the median wall time. The charts are stamped
  **FAKE DATA** whenever the folder has `FAKE_DATA.txt` or "FAKE" in `machine.txt`. The
  physical-core line is drawn from `machine.txt` (`Core(s) per socket` x `Socket(s)`); if
  it is beyond the measured np, a note is printed instead.
- **Live demo:** 30 FPS cap (`TARGET_FPS`). A frame (2 steps + repaint) takes ~5 ms on the
  90 m grid, so a 2.5 h storm (540 steps) lasts ~9 s at 2 steps/frame and ~18 s at 1. The
  prompt's "~20 s" estimate assumed slower steps; set `TARGET_FPS` lower for a longer show.
- `make all` does not fail when raylib is missing: it prints a warning and skips `live`.
  `make live` fails with the install hint.

## Tested (WSL Ubuntu 24.04, gcc 13.3, Python 3, NumPy 1.26, Matplotlib 3.6)
- `make serial`, `build/test_sim --no-timing` (all checks passed), dev run above (64
  storms, 104 s). All four map scripts on `results/dev`; figures opened and checked.
  Grid-mismatch guard (90 m results + 30 m meta -> clear error). Missing `--grid` ->
  map without hillshade. Messy spots file (blank, non-numeric, outside grid, verified=yes)
  -> correct skips and headline.
- `plot_timings.py` on `results_fake/bench` (45 fake runs) **and** on a tiny real
  benchmark: `scripts/run_benchmarks.sh --limit 12 --reps 1 --nps "1 2 4"` on the 90 m grid
  (np4 2.9x speed-up, both modes).
- `src/live.c`: compiles with zero warnings (`-Wall -Wextra -Wpedantic`) against a
  stub `raylib.h` (raylib 4.5 signatures). A headless run of the real loop with no-op
  raylib functions went raining -> draining -> finished with sensible flooded-cell counts.

## Not tested
- **`make live` / `build/live` with real raylib: raylib is not installed on this machine**,
  so the window, texture, keys and text drawing have never actually run.
- Timing charts on Member 2's full benchmark (only fake data + the 5-run mini benchmark).
- Map scripts on the 30 m full results (`results/full` does not exist yet); only the
  90 m 64-storm run.

## Notes for the team
- `results_fake/` is not in `.gitignore` (owned by M1): please add it, or delete the
  folder before committing.
- This checkout had `core.autocrlf=true`, which gave `scripts/run_benchmarks.sh` CRLF line
  endings (`set: pipefail: invalid option name` in WSL). I set `core.autocrlf input`;
  re-checkout the file (`git checkout -- scripts/run_benchmarks.sh`) to get LF back.
- WSL's `lscpu` reports `Core(s) per socket: 9` on this laptop, so `plot_timings.py` marks
  9 physical cores, not 14.
- Dev-run validation (unverified spots, 90 m): Silk Board rank 276 of 4092 (top 10%),
  Bellandur 506, Koramangala 1731, Marathahalli 3002, Hebbal 3015. A block 1 km from the
  Bellandur point ranks 13th, so checking the coordinates may change these results.
