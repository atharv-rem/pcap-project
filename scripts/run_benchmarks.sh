#!/usr/bin/env bash
# [M2] Benchmark sweep for build/flood_mpi.
#
# usage: scripts/run_benchmarks.sh [--grid data/grid.bin] [--meta data/grid.meta] [--limit K]
#            [--reps 3] [--nps "1 2 4 6 8 10 12 14"] [--extra "flags"] [--pause 5]
#
# For every repetition R and every np N it runs build/flood_mpi in dynamic and static mode
# (np=1 only once, as dynamic: with one process the mode makes no difference) and writes
# each run into results/bench/np{N}_{mode}_rep{R}/ (the five files of contract C4).
# --extra is passed to flood_mpi as-is, e.g. --extra "--n-intensity 4 --n-duration 3".
# Timings on the laptop vary by up to 2x, hence the repetitions and the pause between runs.
set -euo pipefail

GRID=data/grid.bin
META=data/grid.meta
LIMIT=0
REPS=3
NPS="1 2 4 6 8 10 12 14"
EXTRA=""
PAUSE=5
BENCH=results/bench

while [ $# -gt 0 ]; do
    case "$1" in
        --grid)  GRID=$2;  shift 2 ;;
        --meta)  META=$2;  shift 2 ;;
        --limit) LIMIT=$2; shift 2 ;;
        --reps)  REPS=$2;  shift 2 ;;
        --nps)   NPS=$2;   shift 2 ;;
        --extra) EXTRA=$2; shift 2 ;;
        --pause) PAUSE=$2; shift 2 ;;
        --out)   BENCH=$2; shift 2 ;;
        -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
        *) echo "run_benchmarks.sh: unknown option $1" >&2; exit 2 ;;
    esac
done

if [ ! -x build/flood_mpi ]; then
    echo "run_benchmarks.sh: build/flood_mpi not found, run 'make mpi' first" >&2
    exit 1
fi
for f in "$GRID" "$META"; do
    [ -f "$f" ] || { echo "run_benchmarks.sh: missing $f" >&2; exit 1; }
done

CORES=$(nproc)
mkdir -p "$BENCH"
lscpu > "$BENCH/machine.txt"
echo "run_benchmarks.sh: $CORES cores, nps='$NPS', reps=$REPS, limit=$LIMIT, extra='$EXTRA'"

# Open MPI refuses to run as root unless told to (WSL often logs in as root).
ROOT_FLAG=""
if [ "$(id -u)" -eq 0 ]; then
    ROOT_FLAG="--allow-run-as-root"
fi

# Build the list of runs first so the progress message can say "run i of n".
RUNS=()
for rep in $(seq 1 "$REPS"); do
    for np in $NPS; do
        if [ "$np" -eq 1 ]; then
            RUNS+=("$np dynamic $rep")
        else
            RUNS+=("$np dynamic $rep" "$np static $rep")
        fi
    done
done

i=0
for run in "${RUNS[@]}"; do
    read -r np mode rep <<< "$run"
    i=$((i + 1))
    out="$BENCH/np${np}_${mode}_rep${rep}"
    OVERSUB=""
    if [ "$np" -gt "$CORES" ]; then
        OVERSUB="--oversubscribe"                   # only when np > cores
    fi

    echo "[$i/${#RUNS[@]}] np=$np mode=$mode rep=$rep -> $out"
    # shellcheck disable=SC2086  # EXTRA / flags are meant to be split into words
    # --use-hwthread-cpus: without it Open MPI allows only as many ranks as it sees physical
    # cores (WSL reports 9 on this 14-core laptop), so np 10..14 would be refused.
    mpirun $ROOT_FLAG --use-hwthread-cpus $OVERSUB -np "$np" build/flood_mpi \
        --grid "$GRID" --meta "$META" --mode "$mode" --limit "$LIMIT" --out "$out/" $EXTRA \
        > "$out.log" 2>&1 || { echo "  run failed, see $out.log" >&2; exit 1; }
    wall=$(tail -n 1 "$out/run_info.csv" | cut -d, -f4)
    echo "  wall ${wall} s"

    if [ "$i" -lt "${#RUNS[@]}" ]; then
        sleep "$PAUSE"                              # let the laptop cool down
    fi
done
echo "run_benchmarks.sh: done, results in $BENCH/"
