#!/usr/bin/env python3
"""Turn OpenStreetMap lakes into a lake mask for a grid.

usage: python3 scripts/lake_mask.py [--osm data/raw/lakes_osm.json] [--meta data/grid.meta]
                                    [--out <meta folder>/lakes_mask.bin]

--osm is an Overpass API answer (`out geom;`) with natural=water / landuse=reservoir ways
and multipolygon relations. A cell is lake when its centre lies inside a water polygon (and
not inside one of its inner rings). Output: uint8, rows*cols, row-major, 1 = lake.
make_risk_map.py, rank_areas.py and validate.py pick it up automatically from the meta
file's folder. Lakes are already water, so counting them as "flooded" is meaningless.
"""
import argparse
import json
import os
import sys

import numpy as np
from matplotlib.path import Path

from rank_areas import read_meta


def rings_from_segments(segs):
    """Join open way segments that share end points into closed rings."""
    segs = [list(s) for s in segs if len(s) >= 2]
    rings = []
    while segs:
        ring = segs.pop(0)
        changed = True
        while ring[0] != ring[-1] and changed:
            changed = False
            for i, s in enumerate(segs):
                if s[0] == ring[-1]:
                    ring += s[1:]
                elif s[-1] == ring[-1]:
                    ring += s[::-1][1:]
                elif s[-1] == ring[0]:
                    ring = s[:-1] + ring
                elif s[0] == ring[0]:
                    ring = s[::-1][:-1] + ring
                else:
                    continue
                segs.pop(i)
                changed = True
                break
        if ring[0] == ring[-1] and len(ring) >= 4:
            rings.append(ring)
    return rings


def polygons(osm):
    """[(outer_rings, inner_rings)] with points as (lon, lat)."""
    out = []
    for e in osm["elements"]:
        if e["type"] == "way" and "geometry" in e:
            pts = [(p["lon"], p["lat"]) for p in e["geometry"]]
            if len(pts) >= 4 and pts[0] == pts[-1]:
                out.append(([pts], []))
        elif e["type"] == "relation":
            segs = {"outer": [], "inner": []}
            for m in e.get("members", []):
                if m.get("type") == "way" and "geometry" in m:
                    role = "inner" if m.get("role") == "inner" else "outer"
                    segs[role].append([(p["lon"], p["lat"]) for p in m["geometry"]])
            outer = rings_from_segments(segs["outer"])
            if outer:
                out.append((outer, rings_from_segments(segs["inner"])))
    return out


def fill(mask, ring, meta, value):
    """Set mask cells whose centre is inside ring (list of (lon, lat)) to value."""
    lon = np.array([p[0] for p in ring])
    lat = np.array([p[1] for p in ring])
    d = meta["cell_deg"]
    c0 = max(0, int((lon.min() - meta["lon_left"]) / d))
    c1 = min(meta["cols"], int((lon.max() - meta["lon_left"]) / d) + 1)
    r0 = max(0, int((meta["lat_top"] - lat.max()) / d))
    r1 = min(meta["rows"], int((meta["lat_top"] - lat.min()) / d) + 1)
    if c0 >= c1 or r0 >= r1:
        return
    cc, rr = np.meshgrid(np.arange(c0, c1), np.arange(r0, r1))
    pts = np.column_stack([meta["lon_left"] + (cc.ravel() + 0.5) * d,
                           meta["lat_top"] - (rr.ravel() + 0.5) * d])
    inside = Path(np.column_stack([lon, lat])).contains_points(pts).reshape(cc.shape)
    mask[r0:r1, c0:c1][inside] = value


def main():
    ap = argparse.ArgumentParser(description="Rasterise OSM lakes onto the grid.")
    ap.add_argument("--osm", default="data/raw/lakes_osm.json")
    ap.add_argument("--meta", default="data/grid.meta")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    if not os.path.isfile(a.osm):
        sys.exit(f"lake_mask.py: {a.osm} not found (download it with the Overpass query in "
                 f"docs/notes_M3.md)")
    meta = read_meta(a.meta)
    out = a.out or os.path.join(os.path.dirname(a.meta) or ".", "lakes_mask.bin")

    with open(a.osm, encoding="utf-8") as f:
        polys = polygons(json.load(f))
    mask = np.zeros((meta["rows"], meta["cols"]), dtype=np.uint8)
    for outer, inner in polys:
        for ring in outer:
            fill(mask, ring, meta, 1)
        for ring in inner:              # islands
            fill(mask, ring, meta, 0)
    mask.tofile(out)
    n = int(mask.sum())
    km2 = n * meta["cell_size_m"] ** 2 / 1e6
    print(f"{len(polys)} water polygons -> {n} lake cells ({100 * n / mask.size:.1f}% of the "
          f"map, {km2:.1f} km2); wrote {out}")


if __name__ == "__main__":
    main()
