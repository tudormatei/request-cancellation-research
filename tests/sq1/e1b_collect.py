#!/usr/bin/env python3
"""Collects E1b detection-latency data (K sweep and T_max sweep)."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import FRAMEWORKS, run_cell

REPO = Path(__file__).parent.parent.parent
OUTPUT_DIR = REPO / "experiments" / "sq1" / "e1b"

CANCEL_AFTER = 5.0
CPU_DURATION_S = 15
SETTLE = 8.0


def main() -> None:
    parser = argparse.ArgumentParser(description="E1b data collection")
    parser.add_argument("--mode",       required=True, choices=["latency-sweep", "tmax-sweep"])
    parser.add_argument("--K",          required=True, type=int, metavar="K_MS",
                        help="YIELD_INTERVAL_MS set in container")
    parser.add_argument("--T",          type=int, default=1, metavar="T_MAX",
                        help="THREAD_POOL_MAX set in container")
    parser.add_argument("--N",          type=int, default=None,
                        help="Concurrency (default: 1 for latency-sweep, 8 for tmax-sweep)")
    parser.add_argument("--runs",       type=int, default=10)
    parser.add_argument("--frameworks", nargs="+", default=["aspnet", "webflux"],
                        choices=list(FRAMEWORKS))
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_DIR / f"e1b_{args.mode.replace('-', '_')}.csv"

    N = args.N if args.N is not None else (1 if args.mode == "latency-sweep" else 8)

    print(f"\nE1b | mode={args.mode} | K={args.K}ms | N={N} | T={args.T}")
    print(f"cancel_after={CANCEL_AFTER}s | runs={args.runs} | settle={SETTLE}s")
    print(f"frameworks: {args.frameworks}")
    print("─" * 60)

    for fw in args.frameworks:
        run_cell(
            framework=fw, scenario="cpu", N=N,
            cancel_after=CANCEL_AFTER, runs=args.runs, settle=SETTLE,
            output=output, T=args.T, yield_interval_ms=args.K,
            cores=1, cpu_duration_s=CPU_DURATION_S,
        )


if __name__ == "__main__":
    main()
