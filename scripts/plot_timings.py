#!/usr/bin/env python3
"""[M3] Timing charts from a benchmark tree.

usage: python3 scripts/plot_timings.py BENCH_DIR [--busy-np 8]

BENCH_DIR holds np{N}_{mode}_rep{R}/ folders (contract C4: run_info.csv, timings.csv) and
optionally machine.txt (lscpu output). For every (np, mode) the median wall time over the
repetitions is used. Writes to BENCH_DIR/figures/:
  speedup.png        speed-up vs processes (relative to the np=1 run), with the ideal line
  imbalance.png      max busy / mean busy over the workers, static vs dynamic
  busy_per_rank.png  busy time per worker at --busy-np processes, static next to dynamic
  per_storm.png      average busy time per storm vs processes: if it grows, the storms
                     themselves run slower when many run at once (shared cores, memory,
                     clock speed), which caps the speed-up even with perfect balance
Only measured points are drawn: no smoothing, no extrapolation.
"""
import argparse
import csv
import os
import re
import statistics
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

COLOR = {"dynamic": "#2a78d6", "static": "#eb6834"}
IDEAL = "#8a8985"
INK2 = "#52514e"
RUN_DIR = re.compile(r"^np(\d+)_([a-z]+)_rep(\d+)$")


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def load_runs(bench):
    """[{np, mode, rep, wall, busy: {rank: s}, count: {rank: n}}] for every complete run."""
    runs = []
    for name in sorted(os.listdir(bench)):
        m = RUN_DIR.match(name)
        d = os.path.join(bench, name)
        if not m or not os.path.isdir(d):
            continue
        info_p, tim_p = os.path.join(d, "run_info.csv"), os.path.join(d, "timings.csv")
        if not (os.path.isfile(info_p) and os.path.isfile(tim_p)):
            print(f"skipped {name}: run_info.csv or timings.csv missing (run unfinished?)")
            continue
        info = read_csv(info_p)[0]
        tim = read_csv(tim_p)
        runs.append({"np": int(m.group(1)), "mode": m.group(2), "rep": int(m.group(3)),
                     "wall": float(info["wall_time_s"]), "n": int(info["n_scenarios"]),
                     "busy": {int(r["rank"]): float(r["busy_time_s"]) for r in tim},
                     "count": {int(r["rank"]): int(r["scenarios_run"]) for r in tim}})
    return runs


def physical_cores(bench):
    """Cores per socket x sockets from lscpu output in machine.txt, or None."""
    path = os.path.join(bench, "machine.txt")
    if not os.path.isfile(path):
        return None
    vals = {}
    with open(path) as f:
        for line in f:
            if ":" in line:
                k, v = line.split(":", 1)
                vals[k.strip()] = v.strip()
    try:
        return int(vals["Core(s) per socket"]) * int(vals.get("Socket(s)", "1"))
    except (KeyError, ValueError):
        return None


def is_fake(bench):
    if os.path.isfile(os.path.join(bench, "FAKE_DATA.txt")):
        return True
    path = os.path.join(bench, "machine.txt")
    return os.path.isfile(path) and "FAKE" in open(path).read()


def imbalance(run):
    """max / mean busy time over the ranks that simulate (1..np-1, or rank 0 alone)."""
    workers = [b for r, b in run["busy"].items() if r >= 1] if run["np"] > 1 \
        else [run["busy"][0]]
    mean = sum(workers) / len(workers)
    return max(workers) / mean if mean > 0 else float("nan")


def group(runs):
    g = {}
    for r in runs:
        g.setdefault((r["np"], r["mode"]), []).append(r)
    return g


def median_run(rs):
    """The repetition whose wall time is the median one (lower middle for even counts)."""
    rs = sorted(rs, key=lambda r: r["wall"])
    return rs[(len(rs) - 1) // 2]


def secs(v):
    return f"{v:.0f} s" if v >= 100 else f"{v:.1f} s"


def finish(fig, ax, path, fake):
    if fake:
        fig.text(0.5, 0.5, "FAKE DATA - testing only", ha="center", va="center",
                 fontsize=34, color="#e34948", alpha=0.25, rotation=25, weight="bold")
    ax.grid(True, color="#e4e3df", linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)
    print(f"wrote {path}")


def plot_speedup(g, modes, base, cores, out, fake):
    fig, ax = plt.subplots(figsize=(7.5, 5))
    nps_all = sorted({n for n, _ in g})
    ideal_x = list(range(1, max(nps_all) + 1))
    ax.plot(ideal_x, [max(1, n - 1) for n in ideal_x], ls="--", color=IDEAL, lw=1.5,
            label="ideal (np - 1 workers)")
    best = {}
    for mode in modes:
        pts = [(1, 1.0)] + [(n, base / statistics.median(r["wall"] for r in g[(n, mode)]))
                            for n in nps_all if n > 1 and (n, mode) in g]
        xs, ys = zip(*pts)
        ax.plot(xs, ys, marker="o", ms=6, lw=2, color=COLOR.get(mode), label=mode)
        for n in nps_all:                       # every repetition, faint
            if n > 1 and (n, mode) in g:
                reps = [base / r["wall"] for r in g[(n, mode)]]
                ax.plot([n] * len(reps), reps, ls="", marker="o", ms=3, alpha=0.35,
                        color=COLOR.get(mode))
        best[mode] = (xs[-1], ys[-1])
    # end labels; push the lower one down if the two would overlap
    ends = sorted(best.values(), key=lambda p: -p[1])
    span = (lambda lo, hi: hi - lo)(*ax.get_ylim()) or 1.0
    shift = 0
    for k, (x, y) in enumerate(ends):
        if k and abs(ends[k - 1][1] - y) < 0.04 * span:
            shift -= 11
        else:
            shift = 0
        ax.annotate(f"{y:.1f}x", (x, y), xytext=(6, shift), textcoords="offset points",
                    va="center", fontsize=9, color=INK2)
    if cores and cores <= max(nps_all):
        ax.axvline(cores, color=INK2, lw=1, ls=":")
        ax.text(cores, 0.98, f" {cores} physical cores", transform=ax.get_xaxis_transform(),
                va="top", fontsize=8.5, color=INK2)
    elif cores:
        ax.text(0.99, 0.02, f"machine.txt: {cores} physical cores (beyond the measured range)",
                transform=ax.transAxes, ha="right", fontsize=8, color=INK2)
    ax.set_xticks(nps_all)
    ax.set_xlabel("processes (one is the coordinator)")
    ax.set_ylabel("speed-up vs 1 process (median wall time)")
    ax.legend(loc="upper left", fontsize=9, frameon=False)
    parts = [f"{m} {best[m][1]:.1f}x" for m in modes]
    n_last = max(best[m][0] for m in modes)
    ax.set_title(f"At {n_last} processes the run is {' and '.join(parts)} faster than on one",
                 fontsize=11)
    finish(fig, ax, os.path.join(out, "speedup.png"), fake)


def plot_imbalance(g, modes, out, fake):
    fig, ax = plt.subplots(figsize=(7.5, 5))
    worst = {}
    for mode in modes:
        pts = [(n, statistics.median(imbalance(r) for r in g[(n, mode)]))
               for n in sorted({n for n, m in g if m == mode}) if n > 1]
        if not pts:
            continue
        xs, ys = zip(*pts)
        ax.plot(xs, ys, marker="o", ms=6, lw=2, color=COLOR.get(mode), label=mode)
        worst[mode] = max(ys)
    ax.axhline(1.0, color=IDEAL, ls="--", lw=1.2)
    ax.text(ax.get_xlim()[0], 1.0, " perfect balance", va="bottom", fontsize=8.5, color=INK2)
    ax.set_xticks(sorted({n for n, _ in g if n > 1}))
    ax.set_xlabel("processes (one is the coordinator)")
    ax.set_ylabel("load imbalance (max / mean worker busy time)")
    ax.legend(loc="upper left", fontsize=9, frameon=False)
    if "static" in worst and "dynamic" in worst:
        title = (f"Static blocks overload the busiest worker up to {worst['static']:.2f}x the "
                 f"mean; dynamic stays within {worst['dynamic']:.2f}x")
    else:
        title = "Load imbalance: " + ", ".join(f"{m} up to {v:.2f}x" for m, v in worst.items())
    ax.set_title(title, fontsize=10.5)
    finish(fig, ax, os.path.join(out, "imbalance.png"), fake)


def plot_busy(g, modes, busy_np, out, fake):
    have = [m for m in modes if (busy_np, m) in g]
    if not have:
        print(f"busy_per_rank.png skipped: no runs with np={busy_np} "
              f"(use --busy-np with one of {sorted({n for n, _ in g if n > 1})})")
        return
    fig, ax = plt.subplots(figsize=(7.5, 5))
    ranks = list(range(1, busy_np))
    width = 0.8 / len(have)
    peak = {}
    for k, mode in enumerate(have):
        run = median_run(g[(busy_np, mode)])
        vals = [run["busy"].get(r, 0.0) for r in ranks]
        x = np.array(ranks) + (k - (len(have) - 1) / 2) * width
        ax.bar(x, vals, width=width * 0.92, color=COLOR.get(mode),
               label=f"{mode} (rep {run['rep']}, wall {run['wall']:.1f} s)")
        peak[mode] = max(vals)
    ax.set_xticks(ranks)
    ax.set_ylim(0, max(peak.values()) * 1.18)    # room for the legend above the bars
    ax.set_xlabel("worker rank (rank 0 is the coordinator and simulates nothing)")
    ax.set_ylabel("busy time (s)")
    ax.legend(loc="upper left", fontsize=9, frameon=False)
    if "static" in peak and "dynamic" in peak:
        title = (f"At {busy_np} processes the busiest static worker needs {secs(peak['static'])}, "
                 f"with dynamic {secs(peak['dynamic'])}")
    else:
        title = f"Busy time per worker at {busy_np} processes"
    ax.set_title(title, fontsize=11)
    finish(fig, ax, os.path.join(out, "busy_per_rank.png"), fake)


def plot_per_storm(g, modes, out, fake):
    """Average busy seconds per storm (all workers' busy time / storms run) against np."""
    fig, ax = plt.subplots(figsize=(7.5, 5))
    base = None
    worst = (1, 0.0)
    for mode in modes:
        pts = []
        for n in sorted({n for n, _ in g}):
            rs = g.get((n, mode)) or (g.get((1, "dynamic")) if n == 1 else None)
            if not rs:
                continue
            per = statistics.median(
                sum(b for rk, b in r["busy"].items() if rk >= 1 or r["np"] == 1) / r["n"]
                for r in rs)
            pts.append((n, per))
        xs, ys = zip(*pts)
        ax.plot(xs, ys, marker="o", ms=6, lw=2, color=COLOR.get(mode), label=mode)
        if xs[0] == 1:
            base = ys[0]
        if ys[-1] > worst[1]:
            worst = (xs[-1], ys[-1])
    if base:
        ax.axhline(base, color=IDEAL, ls="--", lw=1.2)
        ax.text(ax.get_xlim()[0], base, " one process alone", va="bottom", fontsize=8.5,
                color=INK2)
    ax.set_ylim(0, None)
    ax.set_xticks(sorted({n for n, _ in g}))
    ax.set_xlabel("processes (one is the coordinator)")
    ax.set_ylabel("average time per storm (s)")
    ax.legend(loc="upper left", fontsize=9, frameon=False)
    if base:
        ax.set_title(f"Each storm takes {worst[1] / base:.1f}x longer with {worst[0] - 1} workers "
                     f"busy than alone:\nthe shared laptop, not MPI, caps the speed-up",
                     fontsize=10)
    finish(fig, ax, os.path.join(out, "per_storm.png"), fake)


def main():
    ap = argparse.ArgumentParser(description="Plot speed-up and load balance charts.")
    ap.add_argument("bench_dir")
    ap.add_argument("--busy-np", type=int, default=8)
    a = ap.parse_args()
    if not os.path.isdir(a.bench_dir):
        sys.exit(f"plot_timings.py: {a.bench_dir} is not a directory")

    runs = load_runs(a.bench_dir)
    if not runs:
        sys.exit(f"plot_timings.py: no np*_*_rep*/ folders with results in {a.bench_dir}")
    fake = is_fake(a.bench_dir)
    if fake:
        print("!" * 60 + "\n!!  FAKE benchmark data: charts are stamped FAKE DATA  !!\n" + "!" * 60)
    g = group(runs)
    modes = [m for m in ("dynamic", "static") if any(k[1] == m for k in g if k[0] > 1)]
    out = os.path.join(a.bench_dir, "figures")
    os.makedirs(out, exist_ok=True)
    cores = physical_cores(a.bench_dir)

    print(f"{len(runs)} runs; median wall time per (np, mode):")
    for (n, m) in sorted(g):
        walls = [r["wall"] for r in g[(n, m)]]
        print(f"  np={n:>2} {m:<8} median {statistics.median(walls):8.2f} s over "
              f"{len(walls)} reps, imbalance "
              f"{statistics.median(imbalance(r) for r in g[(n, m)]):.3f}")

    base_runs = [r for (n, _), rs in g.items() if n == 1 for r in rs]
    if base_runs:
        plot_speedup(g, modes, statistics.median(r["wall"] for r in base_runs), cores, out,
                     fake)
    else:
        print("speedup.png skipped: no np1_* run to compare against")
    plot_imbalance(g, modes, out, fake)
    plot_busy(g, modes, a.busy_np, out, fake)
    plot_per_storm(g, modes, out, fake)


if __name__ == "__main__":
    main()
