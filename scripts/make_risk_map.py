#!/usr/bin/env python3
"""[M3] Draw the flood-risk map from freq.bin.

usage: python3 scripts/make_risk_map.py RESULTS_DIR [--grid data/grid.bin]
           [--meta data/grid.meta] [--spots data/known_spots.csv]
           [--out RESULTS_DIR/risk_map.png]

Colour = fraction of storms in which each cell floods (0 = never, light blue; 1 = in every
storm, dark red). Cells that never flood are transparent, so the background shows through:
a muted OpenStreetMap street map if scripts/osm_basemap.py has made one (--basemap osm),
otherwise the grey hillshade of the terrain from --grid (--basemap hillshade). Known spots with coordinates
inside the grid are marked. The grid and meta must be the ones the results were made with.
"""
import argparse
import csv
import math
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.image as mpimg  # noqa: E402
import matplotlib.patheffects as pe  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LightSource, LinearSegmentedColormap  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

from matplotlib.colors import ListedColormap  # noqa: E402

from rank_areas import (load_float_grid, load_lakes, load_result, load_spots,  # noqa: E402
                        read_meta)

LAKE_COLOR = "#3f4a5a"   # slate: clearly not part of the blue -> red risk scale

TITLE = "Bengaluru flood-risk map (screening, simple water model)"
MAX_LABELLED = 15   # more known spots than this are drawn as small dots without names
# Light blue -> orange -> dark red; lightness falls steadily, so it reads as one scale.
RISK_CMAP = LinearSegmentedColormap.from_list(
    "risk", ["#b7d3f6", "#5598e7", "#eb6834", "#b3261e", "#5c0a0a"])


# Label positions tried in order (points from the marker): right, left, below-right, ...
LABEL_OFFSETS = [((7, 3), "left"), ((-7, 3), "right"), ((7, -11), "left"),
                 ((-7, -11), "right"), ((7, 13), "left"), ((-7, 13), "right")]


def place_labels(fig, ax, spots, halo):
    """Name each spot, moving a label to the next position if it would overlap a label
    already placed, another spot's marker, or the edge of the map."""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    ax_box = ax.get_window_extent(renderer)
    marks = [ax.transData.transform((s["lon"], s["lat"])) for s in spots]
    r = 6 * fig.dpi / 72                       # marker radius in pixels
    taken = []
    for i, s in enumerate(spots):
        text = s["name"] + ("" if s["verified"] else " (unverified)")
        for (dx, dy), ha in LABEL_OFFSETS:
            t = ax.annotate(text, (s["lon"], s["lat"]), xytext=(dx, dy),
                            textcoords="offset points", ha=ha, va="bottom", fontsize=9,
                            color="#0b0b0b", path_effects=halo, zorder=6)
            bb = t.get_window_extent(renderer).expanded(1.05, 1.15)
            hits_mark = any(j != i and bb.x0 - r < x < bb.x1 + r and bb.y0 - r < y < bb.y1 + r
                            for j, (x, y) in enumerate(marks))
            inside = (bb.x0 >= ax_box.x0 and bb.x1 <= ax_box.x1 and
                      bb.y0 >= ax_box.y0 and bb.y1 <= ax_box.y1)
            if inside and not hits_mark and not any(bb.overlaps(o) for o in taken):
                break
            if (dx, dy) != LABEL_OFFSETS[-1][0]:
                t.remove()                     # keep the last try if nothing fits
        taken.append(bb)


def load_osm(osm_dir, meta):
    """Muted OpenStreetMap picture covering exactly the grid, or None (with a note)."""
    pic, info = os.path.join(osm_dir, "basemap_muted.png"), os.path.join(osm_dir, "basemap.txt")
    if not (os.path.isfile(pic) and os.path.isfile(info)):
        return None
    ext = {}
    with open(info) as f:
        for line in f:
            if "=" in line:
                k, v = line.split("=", 1)
                ext[k.strip()] = v.strip()
    want = {"lat_top": meta["lat_top"], "lon_left": meta["lon_left"],
            "lat_bottom": meta["lat_top"] - meta["rows"] * meta["cell_deg"],
            "lon_right": meta["lon_left"] + meta["cols"] * meta["cell_deg"]}
    if any(abs(float(ext.get(k, "nan")) - v) > 1e-5 or k not in ext for k, v in want.items()):
        print(f"note: {pic} covers a different area than the grid, not used "
              f"(rerun osm_basemap.py --meta ...)")
        return None
    return mpimg.imread(pic)


def run_summary(results_dir):
    """One line describing the storms, from scenarios.csv (empty if it is missing)."""
    path = os.path.join(results_dir, "scenarios.csv")
    if not os.path.isfile(path):
        return ""
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return ""
    ints = [float(r["intensity_mm_hr"]) for r in rows]
    durs = [float(r["duration_hr"]) for r in rows]
    return (f"{len(rows)} storms: {min(ints):g}-{max(ints):g} mm/h for {min(durs):g}-"
            f"{max(durs):g} h  |  not a forecast; elevation only, no drains or buildings")


def main():
    ap = argparse.ArgumentParser(description="Plot the flood-frequency map.")
    ap.add_argument("results_dir")
    ap.add_argument("--grid", default="data/grid.bin")
    ap.add_argument("--meta", default="data/grid.meta")
    ap.add_argument("--spots", default="data/known_spots.csv")
    ap.add_argument("--out", default=None)
    ap.add_argument("--lakes", default="",
                    help="lake mask (default: lakes_mask.bin next to --meta; 'none' = off)")
    ap.add_argument("--basemap", choices=["auto", "osm", "hillshade", "none"], default="auto",
                    help="background: auto = OpenStreetMap if available, else hillshade")
    ap.add_argument("--osm-dir", default="data/raw/osm",
                    help="folder with basemap_muted.png + basemap.txt (osm_basemap.py)")
    a = ap.parse_args()
    out = a.out or os.path.join(a.results_dir, "risk_map.png")

    meta = read_meta(a.meta)
    freq = load_result(a.results_dir, "freq.bin", meta, a.meta)
    spots = load_spots(a.spots, meta, quiet=True)
    lakes = load_lakes(a.lakes, a.meta, meta)
    rows, cols, deg = meta["rows"], meta["cols"], meta["cell_deg"]
    extent = [meta["lon_left"], meta["lon_left"] + cols * deg,
              meta["lat_top"] - rows * deg, meta["lat_top"]]
    lat_mid = meta["lat_top"] - rows * deg / 2

    fig, ax = plt.subplots(figsize=(8.3, 7.8))
    fig.patch.set_facecolor("white")

    osm = load_osm(a.osm_dir, meta) if a.basemap in ("auto", "osm") else None
    if a.basemap == "osm" and osm is None:
        sys.exit(f"make_risk_map.py: no usable OpenStreetMap basemap in {a.osm_dir}; run "
                 f"python3 scripts/osm_basemap.py first")
    if osm is not None:
        ax.imshow(osm, extent=extent, interpolation="bilinear")
    elif a.basemap == "none":
        pass
    elif os.path.isfile(a.grid):
        z = load_float_grid(a.grid, meta, "the --grid file").astype(np.float64)
        ls = LightSource(azdeg=315, altdeg=45)
        shade = ls.hillshade(z, vert_exag=4.0, dx=meta["cell_size_m"], dy=meta["cell_size_m"])
        # soft: squeeze the grey into the light end so the colours stay readable
        ax.imshow(0.55 + 0.45 * shade, cmap="gray", vmin=0, vmax=1, extent=extent,
                  interpolation="bilinear")
    else:
        print(f"note: {a.grid} not found, drawing without hillshade")

    hide = freq <= 0.0 if lakes is None else (freq <= 0.0) | lakes
    shown = np.ma.masked_where(hide, freq)
    im = ax.imshow(shown, cmap=RISK_CMAP, vmin=0.0, vmax=1.0, extent=extent,
                   interpolation="nearest", alpha=0.9 if osm is not None else 1.0)
    lake_handle = None
    if lakes is not None:
        ax.imshow(np.ma.masked_where(~lakes, lakes.astype(float)),
                  cmap=ListedColormap([LAKE_COLOR]), vmin=0, vmax=1, extent=extent,
                  interpolation="nearest", zorder=3,
                  alpha=0.6 if osm is not None else 1.0)  # lake names stay readable
        lake_handle = Line2D([], [], marker="s", ls="", markersize=8, mfc=LAKE_COLOR,
                             mec=LAKE_COLOR, label="lake (OpenStreetMap), not counted")
    cb = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.02)
    cb.set_label("fraction of storms in which the cell floods", fontsize=11)

    halo = [pe.withStroke(linewidth=3, foreground="white")]
    if len(spots) > MAX_LABELLED:          # many points: small dots, no names
        ver = [s for s in spots if s["verified"]]
        unv = [s for s in spots if not s["verified"]]
        if ver:
            ax.plot([s["lon"] for s in ver], [s["lat"] for s in ver], ls="", marker="o",
                    markersize=3.2, mfc="black", mec="white", mew=0.6, zorder=5,
                    label=f"known flood point, verified ({len(ver)})")
        if unv:
            ax.plot([s["lon"] for s in unv], [s["lat"] for s in unv], ls="", marker="o",
                    markersize=5, mfc="white", mec="black", mew=1.0, zorder=5,
                    label=f"known flood spot, approximate ({len(unv)})")
        handles = ax.get_legend_handles_labels()[0] + ([lake_handle] if lake_handle else [])
        ax.legend(handles=handles, loc="lower right", fontsize=8, framealpha=0.9)
        spots = []
        lake_handle = None
    for s in spots:
        ax.plot(s["lon"], s["lat"], marker="o", markersize=8,
                markerfacecolor="black" if s["verified"] else "white",
                markeredgecolor="black", markeredgewidth=1.5, zorder=5)
    if spots:
        place_labels(fig, ax, spots, halo)
        handles = []
        if any(s["verified"] for s in spots):
            handles.append(Line2D([], [], marker="o", ls="", markersize=7, mfc="black",
                                  mec="black", label="known flood spot (verified)"))
        if not all(s["verified"] for s in spots):
            handles.append(Line2D([], [], marker="o", ls="", markersize=7, mfc="white",
                                  mec="black", mew=1.5,
                                  label="known flood spot (approximate, not yet verified)"))
        if lake_handle:
            handles.append(lake_handle)
            lake_handle = None
        ax.legend(handles=handles, loc="lower right", fontsize=8, framealpha=0.9)
    if lake_handle:
        ax.legend(handles=[lake_handle], loc="lower right", fontsize=8, framealpha=0.9)

    ax.set_aspect(1.0 / math.cos(math.radians(lat_mid)))  # 1 km looks the same both ways
    ax.set_xlabel("longitude (°E)", fontsize=11)
    ax.set_ylabel("latitude (°N)", fontsize=11)
    ax.set_title(TITLE, fontsize=13, pad=22)
    sub = run_summary(a.results_dir)
    if sub:
        ax.text(0.5, 1.012, sub, transform=ax.transAxes, ha="center", va="bottom",
                fontsize=8.5, color="#52514e")
    credit = "\nbasemap (c) OpenStreetMap contributors" if osm is not None else ""
    ax.text(0.0, -0.1, f"grid: {rows} x {cols} cells of {meta['cell_size_m']:g} m  |  "
            f"{meta['source']}{credit}", transform=ax.transAxes, va="top", fontsize=7,
            color="#52514e")
    ax.tick_params(labelsize=9)

    fig.tight_layout()
    fig.savefig(out, dpi=200, bbox_inches="tight", pad_inches=0.15)
    print(f"wrote {out} ({np.count_nonzero(freq > 0)} of {freq.size} cells flood at least "
          f"once, max frequency {float(freq.max()):.3f})")


if __name__ == "__main__":
    main()
