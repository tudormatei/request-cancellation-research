#!/usr/bin/env python3
"""Collects ClientWrite accumulation data under repeated streaming cancellations (WebFlux)."""

import argparse
import subprocess
import time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent))
from _common import FRAMEWORKS, fire_concurrent, _write_csv, _pg_exec

REPO = Path(__file__).parent.parent.parent
OUTPUT_DIR = REPO / "experiments" / "sq2" / "e2b_clientwrite"
OUTPUT = OUTPUT_DIR / "e2b_clientwrite.csv"

CANCEL_AFTER = 2.0
POST_CANCEL = 0.5
MONITOR_AFTER = 120
POLL_INTERVAL = 0.5

FIELDS = [
    "N", "rep",
    "first_clientwrite_at_n",
    "peak_clientwrite_count",
    "cleared_within_120s",
    "stuck_count_at_120s",
    "final_active_count",
]


def count_clientwrite() -> int:
    """Count pg_stat_activity rows in ClientWrite wait state."""
    rows = _pg_exec(
        "SELECT count(*) FROM pg_stat_activity "
        "WHERE wait_event = 'ClientWrite'"
    )
    return int(rows[0]) if rows else 0


def count_active_stream() -> int:
    """Count active generate_series queries (streaming endpoint)."""
    rows = _pg_exec(
        "SELECT count(*) FROM pg_stat_activity "
        "WHERE query LIKE '%generate_series%' AND state != 'idle'"
    )
    return int(rows[0]) if rows else 0


def restart_webflux() -> None:
    """Restart only the WebFlux container to reset R2DBC pool state.
    Uses docker restart (not force-recreate) so postgres is not touched."""
    subprocess.run(
        ["docker", "restart", "thesis_spring_webflux"],
        capture_output=True, check=True,
    )
    time.sleep(15)


def run_sequential_cancellations(N: int, url: str) -> dict:
    """
    Fire N sequential streaming cancellations without resetting the pool between them.
    Returns a dict with onset and accumulation metrics.
    """
    first_clientwrite_at_n = None
    peak_clientwrite = 0
    clientwrite_counts = []

    print(f"  Firing {N} sequential streaming cancellations...")
    for i in range(1, N + 1):
        fire_concurrent(url, 1, CANCEL_AFTER)
        time.sleep(POST_CANCEL)

        cw = count_clientwrite()
        active = count_active_stream()
        clientwrite_counts.append(cw)
        print(f"    cancel {i}/{N}: clientwrite={cw}  active_stream={active}")

        if cw > 0 and first_clientwrite_at_n is None:
            first_clientwrite_at_n = i
        peak_clientwrite = max(peak_clientwrite, cw)

    print(f"  Monitoring for {MONITOR_AFTER}s after final cancellation...")
    deadline = time.time() + MONITOR_AFTER
    stuck_at_120 = None
    final_active = None
    last_cw = peak_clientwrite

    while time.time() < deadline:
        cw = count_clientwrite()
        active = count_active_stream()
        peak_clientwrite = max(peak_clientwrite, cw)
        last_cw = cw
        elapsed = MONITOR_AFTER - (deadline - time.time())
        if int(elapsed) % 20 < 1:
            print(f"    t+{elapsed:.0f}s: clientwrite={cw}  active_stream={active}")
        time.sleep(POLL_INTERVAL)

    stuck_at_120 = count_clientwrite()
    final_active = count_active_stream()
    cleared = 1 if stuck_at_120 == 0 else 0

    print(f"  At t+120s: clientwrite={stuck_at_120}  active_stream={final_active}  "
          f"cleared={cleared}")

    return {
        "first_clientwrite_at_n": first_clientwrite_at_n,
        "peak_clientwrite_count": peak_clientwrite,
        "cleared_within_120s":    cleared,
        "stuck_count_at_120s":    stuck_at_120,
        "final_active_count":     final_active,
    }


def run_experiment(N: int, reps: int) -> None:
    cfg = FRAMEWORKS["webflux"]
    url = f"{cfg['url']}/stream-db"

    print(f"\nE2b-clientwrite | N={N} | reps={reps}")
    print(f"  URL: {url}")
    print(f"  Each rep: {N} sequential cancellations → 120s monitoring → container restart")
    print("─" * 70)

    for rep in range(1, reps + 1):
        print(f"\n── Rep {rep}/{reps} ──")

        print("  Restarting WebFlux container (fresh R2DBC pool)...")
        restart_webflux()

        result = run_sequential_cancellations(N, url)

        _write_csv(OUTPUT, FIELDS, {
            "N":   N,
            "rep": rep,
            **result,
        })

        print(f"  Rep {rep} result: "
              f"first_cw_at={result['first_clientwrite_at_n']}  "
              f"peak={result['peak_clientwrite_count']}  "
              f"cleared={result['cleared_within_120s']}  "
              f"stuck_at_120s={result['stuck_count_at_120s']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="E2b ClientWrite accumulation")
    parser.add_argument("--N",    required=True, type=int,
                        help="Number of sequential cancellations per rep")
    parser.add_argument("--reps", type=int, default=5,
                        help="Number of repetitions (container restart between each)")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    run_experiment(args.N, args.reps)


if __name__ == "__main__":
    main()
