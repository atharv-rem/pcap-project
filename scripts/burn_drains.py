#!/usr/bin/env python3
"""Cut OpenStreetMap drains, streams and rivers into an elevation grid ("stream burning").

usage: python3 scripts/burn_drains.py --grid data_fabdem/grid.bin --meta data_fabdem/grid.meta
           --out data_fabdem_drains/ [--osm data/raw/waterways_osm.json] [--depth 2.0]

The elevation data cannot see Bengaluru's storm-water drains (rajakaluves): they are a few
metres wide and lined, so water that would run away along them collects in the model
instead. Every grid cell crossed by a mapped waterway (waterway=drain, stream, river, canal,
ditch; culverts included) is lowered by --depth metres, so water can flow away along the
real drain network. Lines are traced 4-connected because water in the model only moves
north, south, east or west.
--osm is an Overpass API answer (`out geom;`), e.g. from:
  [out:json][timeout:120];way["waterway"~"^(drain|canal|stream|river|ditch)$"](S,W,N,E);out geom;
Writes OUT/grid.bin, OUT/grid.meta (source= notes the burning), OUT/drains_mask.bin
(uint8, 1 = burned) and copies lakes_mask.bin from the input folder if present.
"""
import argparse
import json
import os
import shutil
import sys

import numpy as np

from rank_areas import load_float_grid, read_meta

TYPES = ("drain", "canal", "stream", "river", "ditch")


def trace(mask, pts, meta):
    """Mark every cell the polyline pts [(lat, lon)] passes through, 4-connected."""
    d = meta["cell_deg"]
    prev = None
    for (la0, lo0), (la1, lo1) in zip(pts, pts[1:]):
        steps = max(2, int(max(abs(la1 - la0), abs(lo1 - lo0)) / (d / 4)) + 1)
        for t in np.linspace(0.0, 1.0, steps):
            r = int((meta["lat_top"] - (la0 + (la1 - la0) * t)) / d)
            c = int((lo0 + (lo1 - lo0) * t - meta["lon_left"]) / d)
            if prev is not None and (r, c) != prev and r != prev[0] and c != prev[1]:
                pr, pc = prev[0], c                    # diagonal move: add the corner cell
                if 0 <= pr < meta["rows"] and 0 <= pc < meta["cols"]:
                    mask[pr, pc] = 1
            if 0 <= r < meta["rows"] and 0 <= c < meta["cols"]:
                mask[r, c] = 1
            prev = (r, c)
        # keep prev across segments of the same line so joints stay connected
    return mask


def main():
    ap = argparse.ArgumentParser(description="Burn OSM waterways into the elevation grid.")
    ap.add_argument("--grid", required=True)
    ap.add_argument("--meta", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--osm", default="data/raw/waterways_osm.json")
    ap.add_argument("--depth", type=float, default=2.0, help="metres to lower drain cells")
    a = ap.parse_args()
    if not os.path.isfile(a.osm):
        sys.exit(f"burn_drains.py: {a.osm} not found (see the Overpass query in the docstring)")

    meta = read_meta(a.meta)
    z = load_float_grid(a.grid, meta, "the --grid file")
    with open(a.osm, encoding="utf-8") as f:
        ways = [e for e in json.load(f)["elements"]
                if e.get("type") == "way" and e.get("tags", {}).get("waterway") in TYPES
                and "geometry" in e]
    mask = np.zeros(z.shape, dtype=np.uint8)
    for w in ways:
        trace(mask, [(p["lat"], p["lon"]) for p in w["geometry"]], meta)

    out_z = (z - a.depth * mask).astype("<f4")
    os.makedirs(a.out, exist_ok=True)
    out_z.tofile(os.path.join(a.out, "grid.bin"))
    mask.tofile(os.path.join(a.out, "drains_mask.bin"))
    with open(a.meta) as f, open(os.path.join(a.out, "grid.meta"), "w") as g:
        for line in f:
            if line.startswith("source="):
                line = line.rstrip("\n") + f", OSM waterways burned {a.depth:g} m\n"
            g.write(line)
    lakes = os.path.join(os.path.dirname(a.meta) or ".", "lakes_mask.bin")
    if os.path.isfile(lakes):
        shutil.copy(lakes, os.path.join(a.out, "lakes_mask.bin"))
    n = int(mask.sum())
    print(f"{len(ways)} waterways -> {n} cells lowered by {a.depth:g} m "
          f"({100 * n / mask.size:.1f}% of the map); wrote {a.out}")


if __name__ == "__main__":
    main()
