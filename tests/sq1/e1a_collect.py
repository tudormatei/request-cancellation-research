#!/usr/bin/env python3
"""Collects E1a cliff data across causal, sweep, and cross-validation modes."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import FRAMEWORKS, run_cell

REPO = Path(__file__).parent.parent.parent
OUTPUT_DIR = REPO / "experiments" / "sq1" / "e1a"

MODE_OUTPUT = {
    "causal-cpu":  "e1a_cpu.csv",
    "causal-async": "e1a_async.csv",
    "nsweep":      "e1a_nsweep.csv",
    "cliff-scan":  "e1a_cliff_scan.csv",
    "k-sweep":     "e1a_cliff_K_sweep.csv",
    "cross-val":   "e1a_cross_val.csv",
    "cliff-dense": "e1a_cliff_dense.csv",
    "t-rem-5s":    "e1a_trem_5s.csv",
    "t-rem-20s":   "e1a_trem_20s.csv",
    "k-dense":     "e1a_cliff_K_dense.csv",
    "c-dense":     "e1a_cliff_C_dense.csv",
    "webflux-sched": "e1f_webflux_scheduler.csv",
    "go-cliff":      "e1g_go_cliff.csv",
    "blind":         "e1a_blind.csv",
    "noinject":      "e1a_noinject.csv",
}

CANCEL_AFTER = {"causal-cpu": 5.0, "causal-async": 6.0,
                "nsweep": 5.0, "cliff-scan": 5.0, "k-sweep": 5.0, "cross-val": 5.0,
                "cliff-dense": 5.0, "t-rem-5s": 5.0, "t-rem-20s": 5.0,
                "k-dense": 5.0, "c-dense": 5.0,
                "webflux-sched": 5.0, "go-cliff": 5.0, "blind": 5.0, "noinject": 5.0}

_PER_RUN_MODES = {"cliff-dense", "t-rem-5s", "t-rem-20s", "k-dense", "c-dense",
                  "webflux-sched", "go-cliff", "blind", "noinject"}
CPU_DURATION_S = 15


def main() -> None:
    parser = argparse.ArgumentParser(description="E1a data collection")
    parser.add_argument("--mode",       required=True, choices=list(MODE_OUTPUT))
    parser.add_argument("--N",          required=True, type=int)
    parser.add_argument("--K",          required=True, type=int, metavar="K_MS",
                        help="YIELD_INTERVAL_MS in container")
    parser.add_argument("--T",          type=int, default=None,
                        help="THREAD_POOL_MAX (default: N for cpu modes, 1 for async)")
    parser.add_argument("--runs",       type=int, default=10)
    parser.add_argument("--cores",      type=int, default=1)
    parser.add_argument("--cpu-s",      type=int, default=CPU_DURATION_S,
                        help="CPU_DURATION_S in container")
    parser.add_argument("--frameworks", nargs="+", default=None,
                        help="Override frameworks (default: both for causal, aspnet only for others)")
    parser.add_argument("--out", default=None,
                        help="Override output basename (no extension). The per-run CSV becomes "
                             "<out>_runs.csv. Used by A1–A4 to split scheduler/framework variants.")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_base = args.out if args.out else MODE_OUTPUT[args.mode].removesuffix(".csv")
    output = OUTPUT_DIR / f"{out_base}.csv"

    scenario = "async" if args.mode == "causal-async" else "cpu"
    T = args.T if args.T is not None else (1 if scenario == "async" else args.N)
    cancel_after = CANCEL_AFTER[args.mode]
    cpu_s = args.cpu_s if scenario == "cpu" else None

    if args.frameworks:
        frameworks = args.frameworks
    elif args.mode in ("causal-cpu", "causal-async"):
        frameworks = ["aspnet", "webflux"]
    else:
        frameworks = ["aspnet"]

    print(f"\nE1a | mode={args.mode} | N={args.N} | T={T} | K={args.K}ms | C={args.cores}")
    print(f"scenario={scenario} | cancel_after={cancel_after}s | runs={args.runs}")
    print(f"frameworks: {frameworks}")
    print("─" * 60)

    if args.out:
        per_run_out = OUTPUT_DIR / f"{out_base}_runs.csv" if args.mode in _PER_RUN_MODES else None
    elif args.mode == "k-dense":
        per_run_out = OUTPUT_DIR / f"e1a_cliff_K_dense_K{args.K}_runs.csv"
    elif args.mode == "c-dense":
        per_run_out = OUTPUT_DIR / f"e1a_cliff_C_dense_C{args.cores}_runs.csv"
    elif args.mode in _PER_RUN_MODES:
        per_run_out = OUTPUT_DIR / f"e1a_{args.mode.replace('-','_')}_runs.csv"
    else:
        per_run_out = None

    for fw in frameworks:
        run_cell(
            framework=fw, scenario=scenario, N=args.N,
            cancel_after=cancel_after, runs=args.runs, settle=8.0,
            output=output, T=T, yield_interval_ms=args.K,
            cores=args.cores, cpu_duration_s=cpu_s,
            per_run_output=per_run_out,
        )


if __name__ == "__main__":
    main()
