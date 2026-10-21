#!/usr/bin/env python3
"""[M3] Rank the most flood-prone areas of the map.

usage: python3 scripts/rank_areas.py RESULTS_DIR [--meta data/grid.meta] [--block-m 500]
                                     [--top 20] [--spots data/known_spots.csv]

Splits the grid into square blocks of about --block-m metres (cell_size_m from the meta
file), computes each block's mean flood frequency (freq.bin) and the deepest water in it
(maxdepth.bin), and writes RESULTS_DIR/ranked_areas.csv:
    rank,block_row,block_col,lat,lon,mean_freq,max_depth_m,nearest_known_spot
lat/lon are the block centre; nearest_known_spot is filled only if a known spot lies
within 1 km. Blocks on the right and bottom edge may be smaller than the others.
--by peak ranks by the block's mean peak depth (the deepest water each cell reached in any
storm, from maxdepth.bin) instead, and writes ranked_areas_peak.csv with an extra column
mean_peak_depth_m. Peak depth matched the BBMP flood points better than end-of-storm
flooding (see docs/notes_M3.md).

The helpers in this file (read_meta, load_result, load_spots, block_table, ...) are also
used by validate.py and make_risk_map.py.
"""
import argparse
import csv
import math
import os
import sys
import warnings

import numpy as np

NEAREST_SPOT_MAX_M = 1000.0
MAX_LAKE_SHARE = 0.5      # blocks that are more than half lake are left out of the ranking
EARTH_RADIUS_M = 6371000.0


def die(msg):
    sys.exit(f"{os.path.basename(sys.argv[0])}: {msg}")


def read_meta(path):
    """Contract C1 meta file -> dict (numbers as float, rows/cols as int)."""
    if not os.path.isfile(path):
        die(f"meta file {path} not found")
    meta = {}
    with open(path) as f:
        for line in f:
            if "=" in line:
                k, v = line.split("=", 1)
                meta[k.strip()] = v.strip()
    for k in ("rows", "cols", "cell_size_m", "lat_top", "lon_left", "cell_deg"):
        if k not in meta:
            die(f"{path} has no '{k}=' line")
    out = {k: float(meta[k]) for k in ("cell_size_m", "lat_top", "lon_left", "cell_deg")}
    out["rows"] = int(meta["rows"])
    out["cols"] = int(meta["cols"])
    out["source"] = meta.get("source", "")
    return out


def check_run_info(results_dir, meta, meta_path):
    """Stop if run_info.csv says the results were made on a grid of another size."""
    path = os.path.join(results_dir, "run_info.csv")
    if not os.path.isfile(path):
        return
    with open(path, newline="") as f:
        row = next(csv.DictReader(f), None)
    if row and (int(row["rows"]), int(row["cols"])) != (meta["rows"], meta["cols"]):
        die(f"{results_dir} was made on a {row['rows']} x {row['cols']} grid, but {meta_path} "
            f"describes {meta['rows']} x {meta['cols']}. Pass the --meta (and --grid) the "
            f"results were made with, e.g. --meta data_ds3/grid.meta for the 90 m grid.")


def load_float_grid(path, meta, what):
    """float32 little-endian rows*cols file -> 2-D array; stop if the size is wrong."""
    if not os.path.isfile(path):
        die(f"{path} not found")
    a = np.fromfile(path, dtype="<f4")
    n = meta["rows"] * meta["cols"]
    if a.size != n:
        die(f"{path} holds {a.size} values but the meta file says {meta['rows']} x "
            f"{meta['cols']} = {n}: {what} and the meta file come from different grids.")
    return a.reshape(meta["rows"], meta["cols"])


def load_result(results_dir, name, meta, meta_path):
    check_run_info(results_dir, meta, meta_path)
    return load_float_grid(os.path.join(results_dir, name), meta, name)


def cell_of(lat, lon, meta):
    """(row, col) of the cell containing lat/lon, or None if outside the grid."""
    r = math.floor((meta["lat_top"] - lat) / meta["cell_deg"])
    c = math.floor((lon - meta["lon_left"]) / meta["cell_deg"])
    if 0 <= r < meta["rows"] and 0 <= c < meta["cols"]:
        return r, c
    return None


def load_spots(path, meta, quiet=False):
    """Contract C5 rows with usable coordinates inside the grid. Skipped rows are reported."""
    if not path or not os.path.isfile(path):
        if not quiet:
            print(f"note: no known-spots file at {path}, no spots used")
        return []
    spots = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            name = (row.get("name") or "").strip() or "(no name)"
            lat_s, lon_s = (row.get("lat") or "").strip(), (row.get("lon") or "").strip()
            if not lat_s or not lon_s:
                if not quiet:
                    print(f"skipped spot '{name}': blank lat or lon")
                continue
            try:
                lat, lon = float(lat_s), float(lon_s)
                if not (math.isfinite(lat) and math.isfinite(lon)):
                    raise ValueError
            except ValueError:
                if not quiet:
                    print(f"skipped spot '{name}': lat/lon '{lat_s}', '{lon_s}' are not numbers")
                continue
            rc = cell_of(lat, lon, meta)
            if rc is None:
                if not quiet:
                    print(f"skipped spot '{name}': ({lat}, {lon}) is outside the grid")
                continue
            spots.append({"name": name, "lat": lat, "lon": lon, "row": rc[0], "col": rc[1],
                          "verified": (row.get("verified") or "").strip().lower() == "yes",
                          "source_url": (row.get("source_url") or "").strip(),
                          # "BBMP vulnerable: X" -> "BBMP vulnerable"; others -> "other"
                          "group": name.split(":", 1)[0] if ":" in name else "other"})
    return spots


def distance_m(lat1, lon1, lat2, lon2):
    """Great-circle distance (haversine), metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def load_lakes(lakes_arg, meta_path, meta):
    """Lake mask (bool rows x cols) or None. lakes_arg: path, "" = auto, "none" = off.
    Auto looks for lakes_mask.bin next to the meta file (made by lake_mask.py)."""
    if lakes_arg == "none":
        return None
    path = lakes_arg or os.path.join(os.path.dirname(meta_path) or ".", "lakes_mask.bin")
    if not os.path.isfile(path):
        if lakes_arg:
            die(f"lake mask {path} not found")
        print(f"note: no lake mask at {path}; lakes count as land (see lake_mask.py)")
        return None
    m = np.fromfile(path, dtype=np.uint8)
    if m.size != meta["rows"] * meta["cols"]:
        die(f"{path} does not match the grid in {meta_path}; rerun lake_mask.py --meta "
            f"{meta_path}")
    print(f"lake mask: {path} ({int(m.sum())} lake cells, excluded)")
    return m.reshape(meta["rows"], meta["cols"]).astype(bool)


def block_cells(meta, block_m):
    return max(1, int(round(block_m / meta["cell_size_m"])))


def block_table(freq, maxdepth, meta, block_m, lakes=None, by="freq"):
    """Per-block statistics, sorted from most to least flood-prone.

    Returns (b, blocks) where b is the block side in cells and blocks is a list of dicts
    with keys rank, block_row, block_col, lat, lon, mean_freq, max_depth_m,
    mean_peak_depth_m. Order (by="freq"): mean flood frequency, then deepest water, both
    descending, then block position; by="peak": mean peak depth, then mean frequency.
    With a lake mask, lake cells are ignored and blocks that are more than MAX_LAKE_SHARE
    lake are left out (they are not in the list at all)."""
    rows, cols = freq.shape
    b = block_cells(meta, block_m)
    nbr, nbc = -(-rows // b), -(-cols // b)
    pad = ((0, nbr * b - rows), (0, nbc * b - cols))
    f = freq.astype(np.float64)
    d = maxdepth.astype(np.float64)
    if lakes is not None:
        f = np.where(lakes, np.nan, f)
        d = np.where(lakes, np.nan, d)
        share = np.pad(lakes.astype(np.float64), pad, constant_values=np.nan)
        share = np.nanmean(share.reshape(nbr, b, nbc, b), axis=(1, 3))
    else:
        share = np.zeros((nbr, nbc))
    f = np.pad(f, pad, constant_values=np.nan).reshape(nbr, b, nbc, b)
    d = np.pad(d, pad, constant_values=np.nan).reshape(nbr, b, nbc, b)
    with warnings.catch_warnings():            # all-lake blocks give empty means
        warnings.simplefilter("ignore", category=RuntimeWarning)
        mean_f = np.nanmean(f, axis=(1, 3))
        max_d = np.nanmax(d, axis=(1, 3))
        mean_d = np.nanmean(d, axis=(1, 3))

    blocks = []
    for br in range(nbr):
        r0, r1 = br * b, min((br + 1) * b, rows)
        lat = meta["lat_top"] - (r0 + r1) / 2 * meta["cell_deg"]
        for bc in range(nbc):
            if share[br, bc] > MAX_LAKE_SHARE or np.isnan(mean_f[br, bc]):
                continue
            c0, c1 = bc * b, min((bc + 1) * b, cols)
            lon = meta["lon_left"] + (c0 + c1) / 2 * meta["cell_deg"]
            blocks.append({"block_row": br, "block_col": bc, "lat": lat, "lon": lon,
                           "mean_freq": float(mean_f[br, bc]),
                           "max_depth_m": float(max_d[br, bc]),
                           "mean_peak_depth_m": float(mean_d[br, bc])})
    if by == "peak":
        blocks.sort(key=lambda x: (-x["mean_peak_depth_m"], -x["mean_freq"], x["block_row"],
                                   x["block_col"]))
    else:
        blocks.sort(key=lambda x: (-x["mean_freq"], -x["max_depth_m"], x["block_row"],
                                   x["block_col"]))
    for i, blk in enumerate(blocks):
        blk["rank"] = i + 1
    return b, blocks


def nearest_spot(lat, lon, spots, max_m=NEAREST_SPOT_MAX_M):
    best, best_d = "", max_m
    for s in spots:
        dist = distance_m(lat, lon, s["lat"], s["lon"])
        if dist <= best_d:
            best, best_d = s["name"], dist
    return best


def main():
    ap = argparse.ArgumentParser(description="Rank map blocks by mean flood frequency.")
    ap.add_argument("results_dir")
    ap.add_argument("--meta", default="data/grid.meta")
    ap.add_argument("--block-m", type=float, default=500.0)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--spots", default="data/known_spots.csv")
    ap.add_argument("--lakes", default="",
                    help="lake mask (default: lakes_mask.bin next to --meta; 'none' = off)")
    ap.add_argument("--by", choices=["freq", "peak"], default="freq",
                    help="rank by mean flood frequency (default) or mean peak depth")
    a = ap.parse_args()

    meta = read_meta(a.meta)
    freq = load_result(a.results_dir, "freq.bin", meta, a.meta)
    maxdepth = load_result(a.results_dir, "maxdepth.bin", meta, a.meta)
    spots = load_spots(a.spots, meta, quiet=True)
    lakes = load_lakes(a.lakes, a.meta, meta)

    b, blocks = block_table(freq, maxdepth, meta, a.block_m, lakes, a.by)
    for blk in blocks:
        blk["nearest_known_spot"] = nearest_spot(blk["lat"], blk["lon"], spots)

    peak = a.by == "peak"
    out = os.path.join(a.results_dir, "ranked_areas_peak.csv" if peak else "ranked_areas.csv")
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "block_row", "block_col", "lat", "lon", "mean_freq",
                    "max_depth_m", "nearest_known_spot"] + (["mean_peak_depth_m"] if peak else []))
        for blk in blocks:
            w.writerow([blk["rank"], blk["block_row"], blk["block_col"], f"{blk['lat']:.5f}",
                        f"{blk['lon']:.5f}", f"{blk['mean_freq']:.4f}",
                        f"{blk['max_depth_m']:.3f}", blk["nearest_known_spot"]]
                       + ([f"{blk['mean_peak_depth_m']:.3f}"] if peak else []))

    side = b * meta["cell_size_m"]
    print(f"{len(blocks)} blocks of {b} x {b} cells (~{side:.0f} m), wrote {out}")
    print(f"top {min(a.top, len(blocks))} blocks by "
          f"{'mean peak depth' if peak else 'mean flood frequency'}:")
    print(f"{'rank':>4} {'blk_r':>5} {'blk_c':>5} {'lat':>9} {'lon':>9} {'mean_freq':>9} "
          f"{'peak_m':>6} {'max_depth_m':>11}  nearest known spot (<1 km)")
    for blk in blocks[:a.top]:
        print(f"{blk['rank']:>4} {blk['block_row']:>5} {blk['block_col']:>5} "
              f"{blk['lat']:>9.4f} {blk['lon']:>9.4f} {blk['mean_freq']:>9.4f} "
              f"{blk['mean_peak_depth_m']:>6.2f} {blk['max_depth_m']:>11.2f}  "
              f"{blk['nearest_known_spot']}")


if __name__ == "__main__":
    main()
