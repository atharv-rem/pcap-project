#!/usr/bin/env python3
"""[M3] Flooded area by rain intensity and duration.

usage: python3 scripts/flooded_area_table.py RESULTS_DIR

Reads RESULTS_DIR/scenarios.csv and writes
  RESULTS_DIR/flooded_area_table.csv  rows = intensity (mm/h), columns = duration (h)
  RESULTS_DIR/flooded_area_table.png  the same table as a heatmap
Scenarios that were not run (e.g. --limit) are left empty.
"""
import argparse
import csv
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

BLUES = LinearSegmentedColormap.from_list(
    "blues", ["#cde2fb", "#86b6ef", "#3987e5", "#256abf", "#184f95", "#0d366b"])


def main():
    ap = argparse.ArgumentParser(description="Flooded area table by intensity x duration.")
    ap.add_argument("results_dir")
    a = ap.parse_args()

    path = os.path.join(a.results_dir, "scenarios.csv")
    if not os.path.isfile(path):
        sys.exit(f"flooded_area_table.py: {path} not found")
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        sys.exit(f"flooded_area_table.py: {path} has no scenarios")

    ints = sorted({float(r["intensity_mm_hr"]) for r in rows})
    durs = sorted({float(r["duration_hr"]) for r in rows})
    table = np.full((len(ints), len(durs)), np.nan)
    for r in rows:
        table[ints.index(float(r["intensity_mm_hr"])),
              durs.index(float(r["duration_hr"]))] = float(r["flooded_area_km2"])

    out_csv = os.path.join(a.results_dir, "flooded_area_table.csv")
    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["intensity_mm_hr \\ duration_hr"] + [f"{d:g}" for d in durs])
        for i, inten in enumerate(ints):
            w.writerow([f"{inten:g}"] + ["" if np.isnan(v) else f"{v:.3f}" for v in table[i]])

    fig, ax = plt.subplots(figsize=(1.6 + 0.85 * len(durs), 1.4 + 0.6 * len(ints)))
    im = ax.imshow(table, cmap=BLUES, origin="lower", aspect="auto")
    ax.set_xticks(range(len(durs)), [f"{d:.3g}" for d in durs])
    ax.set_yticks(range(len(ints)), [f"{v:.3g}" for v in ints])
    ax.set_xlabel("rain duration (h)")
    ax.set_ylabel("rain intensity (mm/h)")
    cb = fig.colorbar(im, ax=ax)
    cb.set_label("flooded area (km²)")
    if len(ints) * len(durs) <= 144:   # values readable only on small tables
        vmax = np.nanmax(table)
        for i in range(len(ints)):
            for j in range(len(durs)):
                v = table[i, j]
                if not np.isnan(v):
                    ax.text(j, i, f"{v:.1f}", ha="center", va="center", fontsize=8,
                            color="white" if v > 0.55 * vmax else "#0b0b0b")
    lo, hi = np.nanmin(table), np.nanmax(table)
    ax.set_title(f"Flooded area grows with rain: {lo:.1f} km² to {hi:.1f} km²", fontsize=11)
    ax.tick_params(labelsize=8)
    fig.tight_layout()
    out_png = os.path.join(a.results_dir, "flooded_area_table.png")
    fig.savefig(out_png, dpi=200)
    print(f"{len(ints)} intensities x {len(durs)} durations, {len(rows)} scenarios; "
          f"wrote {out_csv} and {out_png}")


if __name__ == "__main__":
    main()
