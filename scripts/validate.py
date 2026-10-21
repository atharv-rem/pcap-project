#!/usr/bin/env python3
"""[M3] Check the flood-risk ranking against places known to flood.

usage: python3 scripts/validate.py RESULTS_DIR [--meta data/grid.meta] [--block-m 500]
                                   [--spots data/known_spots.csv]

For every known spot with coordinates inside the grid: the block it falls in (same blocks
and order as rank_areas.py), that block's rank among all blocks, its percentile and whether
it is in the top 10% of blocks. Writes RESULTS_DIR/validation.csv and prints a summary.
The headline counts only spots marked verified=yes. Spots that miss are listed with their
rank, not hidden.
"""
import argparse
import csv
import math
import os

from rank_areas import block_table, load_lakes, load_result, load_spots, read_meta

TOP_SHARE = 0.10


def main():
    ap = argparse.ArgumentParser(description="Compare known flood spots with the ranking.")
    ap.add_argument("results_dir")
    ap.add_argument("--meta", default="data/grid.meta")
    ap.add_argument("--block-m", type=float, default=500.0)
    ap.add_argument("--spots", default="data/known_spots.csv")
    ap.add_argument("--lakes", default="",
                    help="lake mask (default: lakes_mask.bin next to --meta; 'none' = off)")
    a = ap.parse_args()

    meta = read_meta(a.meta)
    freq = load_result(a.results_dir, "freq.bin", meta, a.meta)
    maxdepth = load_result(a.results_dir, "maxdepth.bin", meta, a.meta)
    spots = load_spots(a.spots, meta)
    lakes = load_lakes(a.lakes, a.meta, meta)
    b, blocks = block_table(freq, maxdepth, meta, a.block_m, lakes)
    by_pos = {(blk["block_row"], blk["block_col"]): blk for blk in blocks}
    n = len(blocks)
    top_n = max(1, math.ceil(TOP_SHARE * n))

    rows = []
    in_lake = []
    for s in spots:
        blk = by_pos.get((s["row"] // b, s["col"] // b))
        if blk is None:                        # block is mostly lake: not ranked
            in_lake.append(s["name"])
            continue
        rows.append({
            "name": s["name"], "lat": s["lat"], "lon": s["lon"], "group": s["group"],
            "verified": "yes" if s["verified"] else "no",
            "block_row": blk["block_row"], "block_col": blk["block_col"],
            "cell_freq": float(freq[s["row"], s["col"]]),
            "block_mean_freq": blk["mean_freq"], "block_max_depth_m": blk["max_depth_m"],
            "rank": blk["rank"], "n_blocks": n,
            # share of blocks ranked below this one
            "percentile": 100.0 * (n - blk["rank"]) / n,
            "in_top10": "yes" if blk["rank"] <= top_n else "no",
        })

    out = os.path.join(a.results_dir, "validation.csv")
    cols = ["name", "lat", "lon", "verified", "group", "block_row", "block_col", "cell_freq",
            "block_mean_freq", "block_max_depth_m", "rank", "n_blocks", "percentile",
            "in_top10"]
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({**r, "cell_freq": f"{r['cell_freq']:.4f}",
                        "block_mean_freq": f"{r['block_mean_freq']:.4f}",
                        "block_max_depth_m": f"{r['block_max_depth_m']:.3f}",
                        "percentile": f"{r['percentile']:.1f}"})

    side = b * meta["cell_size_m"]
    print(f"{n} blocks of ~{side:.0f} m; top 10% = rank 1..{top_n}. Wrote {out}")
    print(f"{'spot':<24} {'verified':>8} {'rank':>6} {'pct':>6} {'top10%':>6} "
          f"{'blk_freq':>8} {'cell_freq':>9} {'max_d_m':>7}")
    shown = sorted(rows, key=lambda r: r["rank"])
    if len(shown) > 25:
        print(f"(the 15 best-ranked of {len(shown)} spots; all are in {out})")
        shown = shown[:15]
    for r in shown:
        print(f"{r['name'][:24]:<24} {r['verified']:>8} {r['rank']:>6} {r['percentile']:>6.1f} "
              f"{r['in_top10']:>6} {r['block_mean_freq']:>8.4f} {r['cell_freq']:>9.4f} "
              f"{r['block_max_depth_m']:>7.2f}")

    verified = [r for r in rows if r["verified"] == "yes"]
    print()
    if in_lake:
        print(f"{len(in_lake)} spots fall in blocks that are mostly lake and are not ranked: "
              + "; ".join(in_lake[:5]) + (" ..." if len(in_lake) > 5 else ""))
    print(f"{len(verified)} of {len(rows)} usable spots are verified=yes.")
    if verified:
        hits = sum(r["in_top10"] == "yes" for r in verified)
        share = hits / len(verified)
        print(f"HEADLINE: {hits} of {len(verified)} verified known spots are in the top 10% "
              f"of blocks ({100 * share:.0f}%; random places would give ~{100 * top_n / n:.0f}%, "
              f"so {share / (top_n / n):.1f}x better than chance).")
        groups = sorted({r["group"] for r in verified})
        if len(groups) > 1:
            for gname in groups:
                gr = [r for r in verified if r["group"] == gname]
                gh = sum(r["in_top10"] == "yes" for r in gr)
                med = sorted(r["percentile"] for r in gr)[len(gr) // 2]
                print(f"  {gname:<20} {gh:>4} of {len(gr):>4} in top 10% "
                      f"({100 * gh / len(gr):.0f}%), median percentile {med:.0f}")
    else:
        print("HEADLINE: no spot is verified yet, so there is no headline result. "
              "The team must check each point on a map and set verified=yes.")
    if rows:
        hits_all = sum(r["in_top10"] == "yes" for r in rows)
        print(f"(all spots, verified or not, for information only: {hits_all} of {len(rows)} "
              f"in the top 10%)")
    misses = [r for r in rows if r["in_top10"] == "no"]
    if len(misses) > 25:
        print(f"{len(misses)} spots are outside the top 10%; all are listed with their rank in "
              f"{out}. The 10 lowest-ranked:")
        misses = sorted(misses, key=lambda r: r["rank"])[-10:]
    if misses:
        print("Spots outside the top 10% (explain these in the report, e.g. elevation data "
              "cannot show drains, lake outlets or flyovers):")
        for r in sorted(misses, key=lambda r: r["rank"]):
            print(f"  {r['name']}: rank {r['rank']} of {n} ({r['percentile']:.1f} percentile)"
                  f"{'' if r['verified'] == 'yes' else ', unverified'}")


if __name__ == "__main__":
    main()
