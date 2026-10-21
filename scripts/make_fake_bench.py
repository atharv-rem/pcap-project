#!/usr/bin/env python3
"""[M3] FAKE benchmark tree, only for developing plot_timings.py.

usage: python3 scripts/make_fake_bench.py [--out results_fake/bench] [--seed 1]

Writes np{N}_{mode}_rep{R}/run_info.csv + timings.csv (contract C4 format) for np in
1 2 4 6 8 10 12 14, modes dynamic and static (np=1 only as dynamic, like
run_benchmarks.sh), 3 reps, plus a fake machine.txt and a FAKE_DATA.txt marker.
The numbers come from a toy cost model, NOT from flood_mpi: 400 storms (20 x 20,
10-60 mm/h, 1-4 h) on the 90 m grid, a storm costs ~1.6 ms per step and wetter storms
cost more; workers slow down a little as more of them share memory bandwidth; static
gets fixed contiguous blocks (so the heavy high-intensity storms pile up on the last
workers), dynamic hands storms out one at a time. Plus ~4% run-to-run noise.
Real benchmark folders from Member 2 (results/bench/) replace all of this.
"""
import argparse
import math
import os

import numpy as np

NPS = [1, 2, 4, 6, 8, 10, 12, 14]
REPS = 3
N_INT, N_DUR = 20, 20
ROWS, COLS = 372, 396
BANNER = "#" * 70 + "\n#  FAKE BENCHMARK DATA - toy model, not measured. Do not report it.\n" + "#" * 70


def storm_costs():
    """Seconds per storm on one idle core, id = i_int * N_DUR + i_dur (contract C3)."""
    costs = []
    for i in range(N_INT):
        inten = 10 + 50 * i / (N_INT - 1)
        for j in range(N_DUR):
            dur = 1 + 3 * j / (N_DUR - 1)
            steps = math.ceil(dur * 3600 / 30) + 240
            wet = 1.0 + 0.012 * (inten - 10)            # more water -> more wet cells
            costs.append(steps * 1.6e-3 * wet)
    return np.array(costs)


def slowdown(workers):
    """Shared memory bandwidth: every extra busy worker slows all of them a little."""
    return 1.0 + 0.035 * (workers - 1)


def simulate(np_, mode, costs, rng):
    """Returns (wall_s, [(rank, scenarios_run, busy_s), ...])."""
    n = len(costs)
    noise = rng.lognormal(0.0, 0.04)                     # whole-run noise (laptop load)
    if np_ == 1:
        t = costs * slowdown(1) * noise * rng.lognormal(0.0, 0.01, n)
        return t.sum() + 0.15, [(0, n, t.sum())]
    w = np_ - 1
    t = costs * slowdown(w) * noise * rng.lognormal(0.0, 0.02, n)
    busy, count = np.zeros(w), np.zeros(w, dtype=int)
    if mode == "static":
        base, rem = divmod(n, w)
        start = 0
        for k in range(w):
            c = base + (k < rem)
            busy[k], count[k] = t[start:start + c].sum(), c
            start += c
        finish = busy.copy()
    else:
        finish = np.zeros(w)                             # next storm to the first free worker
        for sid in range(n):
            k = int(np.argmin(finish))
            finish[k] += t[sid] + 2e-4                   # + one message round trip
            busy[k] += t[sid]
            count[k] += 1
    wall = finish.max() + 0.15 + 0.01 * np_              # grid load + reduce/gather
    return wall, [(0, 0, 0.0)] + [(k + 1, count[k], busy[k]) for k in range(w)]


def main():
    ap = argparse.ArgumentParser(description="Write a FAKE benchmark tree for testing.")
    ap.add_argument("--out", default="results_fake/bench")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)
    costs = storm_costs()
    print(BANNER)

    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "FAKE_DATA.txt"), "w") as f:
        f.write("This benchmark tree was made by scripts/make_fake_bench.py from a toy model.\n"
                "It is NOT measured data. plot_timings.py stamps FAKE DATA on its charts.\n")
    with open(os.path.join(a.out, "machine.txt"), "w") as f:
        f.write("# FAKE machine.txt written by make_fake_bench.py (lscpu-style)\n"
                "Architecture:                       x86_64\n"
                "CPU(s):                             14\n"
                "Model name:                         FAKE 14-core laptop CPU\n"
                "Thread(s) per core:                 1\n"
                "Core(s) per socket:                 14\n"
                "Socket(s):                          1\n")

    n_runs = 0
    for rep in range(1, REPS + 1):
        for np_ in NPS:
            for mode in (["dynamic"] if np_ == 1 else ["dynamic", "static"]):
                wall, ranks = simulate(np_, mode, costs, rng)
                d = os.path.join(a.out, f"np{np_}_{mode}_rep{rep}")
                os.makedirs(d, exist_ok=True)
                with open(os.path.join(d, "run_info.csv"), "w") as f:
                    f.write("mode,nprocs,n_scenarios,wall_time_s,rows,cols\n"
                            f"{mode},{np_},{len(costs)},{wall:.6f},{ROWS},{COLS}\n")
                with open(os.path.join(d, "timings.csv"), "w") as f:
                    f.write("rank,scenarios_run,busy_time_s\n")
                    for r, c, b in ranks:
                        f.write(f"{r},{c},{b:.6f}\n")
                n_runs += 1
    print(f"wrote {n_runs} FAKE runs to {a.out}/ (np {NPS}, {REPS} reps)")
    print(BANNER)


if __name__ == "__main__":
    main()
