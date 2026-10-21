#!/usr/bin/env python3
"""Compare flood-risk runs against the known flood points, fairly.

usage: python3 scripts/compare_runs.py --meta data_fabdem_ds3/grid.meta RUN_DIR [RUN_DIR ...]
           [--spots data/known_spots.csv] [--radius-m 0 150 300] [--random 20000]

For every verified known spot and for --random random land points (same points for every
run; lakes excluded) the score is the highest flood frequency within --radius-m metres
(0 = the spot's own cell). This tolerates spot coordinates that are slightly off, and the
random points get exactly the same treatment, so a larger radius cannot inflate the result.
Printed per run and radius, separately for two halves of the spots (A = even, B = odd
position in the file; choose settings on A, report B):
  AUC      chance that a known spot scores higher than a random point (ties count half);
           0.5 = no better than guessing, 1.0 = perfect
  --field maxdepth.bin scores by the deepest water a cell reached in any storm instead.
  top10    share of known spots scoring above the 90th percentile of the random points
           (exactly 10% for guessing; ties at the threshold get proportional credit)
"""
import argparse
import os

import numpy as np

from rank_areas import load_lakes, load_result, load_spots, read_meta


def max_within(freq, r_cells):
    """Highest value within a circle of r_cells cells around every cell."""
    if r_cells <= 0:
        return freq
    out = freq.copy()
    rows, cols = freq.shape
    for dr in range(-r_cells, r_cells + 1):
        for dc in range(-r_cells, r_cells + 1):
            if dr * dr + dc * dc > r_cells * r_cells or (dr == 0 and dc == 0):
                continue
            src = freq[max(0, -dr):rows - max(0, dr), max(0, -dc):cols - max(0, dc)]
            dst = out[max(0, dr):rows - max(0, -dr), max(0, dc):cols - max(0, -dc)]
            np.maximum(dst, src, out=dst)
    return out


def auc(pos, neg):
    """P(pos > neg) + 0.5 P(pos == neg), via ranks."""
    allv = np.concatenate([pos, neg])
    order = allv.argsort(kind="mergesort")
    ranks = np.empty(len(allv))
    sv = allv[order]
    i = 0
    while i < len(sv):                       # average ranks over ties
        j = i
        while j + 1 < len(sv) and sv[j + 1] == sv[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1
        i = j + 1
    rp = ranks[:len(pos)].sum()
    return (rp - len(pos) * (len(pos) + 1) / 2.0) / (len(pos) * len(neg))


def main():
    ap = argparse.ArgumentParser(description="Score runs against known flood spots.")
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--meta", default="data/grid.meta")
    ap.add_argument("--spots", default="data/known_spots.csv")
    ap.add_argument("--lakes", default="")
    ap.add_argument("--radius-m", type=float, nargs="+", default=[0, 150, 300])
    ap.add_argument("--random", type=int, default=20000)
    ap.add_argument("--field", default="freq.bin",
                    help="score file: freq.bin (flood frequency) or maxdepth.bin (peak depth)")
    a = ap.parse_args()

    meta = read_meta(a.meta)
    lakes = load_lakes(a.lakes, a.meta, meta)
    spots = [s for s in load_spots(a.spots, meta, quiet=True) if s["verified"]]
    if lakes is not None:
        spots = [s for s in spots if not lakes[s["row"], s["col"]]]
    halves = {"A": spots[0::2], "B": spots[1::2]}
    rng = np.random.default_rng(12345)
    land = np.flatnonzero(~lakes.ravel()) if lakes is not None else \
        np.arange(meta["rows"] * meta["cols"])
    rand = rng.choice(land, size=a.random, replace=False)
    print(f"{len(spots)} verified spots on land (A {len(halves['A'])}, B {len(halves['B'])}); "
          f"{a.random} random land points")
    print(f"{'run':<28} {'radius':>6}  {'AUC A':>6} {'AUC B':>6}  {'top10 A':>7} {'top10 B':>7}")
    for run in a.runs:
        freq = load_result(run, a.field, meta, a.meta).astype(np.float64)
        if lakes is not None:
            freq = np.where(lakes, -1.0, freq)          # lakes never count as high risk
        for rm in a.radius_m:
            s = max_within(freq, int(round(rm / meta["cell_size_m"])))
            neg = s.ravel()[rand]
            thr = np.quantile(neg, 0.9)
            # scores equal to the threshold get the share of credit that makes exactly 10%
            # of the random points count, so ties (many cells at 1.0) stay fair
            above, tied = np.mean(neg > thr), np.mean(neg == thr)
            tie_credit = (0.1 - above) / tied if tied > 0 else 0.0
            res = {}
            for h, pts in halves.items():
                pos = np.array([s[p["row"], p["col"]] for p in pts])
                top = np.mean(pos > thr) + tie_credit * np.mean(pos == thr)
                res[h] = (auc(pos, neg), float(top))
            print(f"{os.path.basename(run.rstrip('/')):<28} {rm:>5.0f}m  "
                  f"{res['A'][0]:>6.3f} {res['B'][0]:>6.3f}  "
                  f"{100 * res['A'][1]:>6.0f}% {100 * res['B'][1]:>6.0f}%")


if __name__ == "__main__":
    main()
