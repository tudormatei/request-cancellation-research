#!/usr/bin/env python3
"""Collects E2a single-result DB cancellation data under concurrent load."""

import argparse
import threading
import time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent))
from _common import (
    FRAMEWORKS, fire_concurrent, collect_logs,
    verify_clean_pg_stat, poll_pg_stat_activity,
    _write_csv, E2A_FIELDS,
)

REPO = Path(__file__).parent.parent.parent
OUTPUT_DIR = REPO / "experiments" / "sq2" / "e2a"
OUTPUT = OUTPUT_DIR / "e2a_db.csv"

CANCEL_AFTER = 6.0
SETTLE = 8.0
POST_WAIT = 2.0


def run_cell(framework: str, N: int, runs: int) -> None:
    fw_key = "spring-mvc" if framework == "mvc" else framework
    cfg = FRAMEWORKS[fw_key]
    url = f"{cfg['url']}/db"
    container = cfg["container"]
    cancel_ms = int(CANCEL_AFTER * 1000)

    print(f"\nE2a | framework={framework} | N={N} | cancel_after={CANCEL_AFTER}s | runs={runs}")
    print("─" * 60)

    for run in range(1, runs + 1):
        verify_clean_pg_stat("pg_sleep")

        since = time.time()
        disconnect_ts = int((since + CANCEL_AFTER) * 1000)

        monitor_result: dict = {}
        monitor_done = threading.Event()

        def _monitor():
            monitor_result.update(poll_pg_stat_activity(disconnect_ts, "pg_sleep", timeout_s=30))
            monitor_done.set()

        monitor_thread = threading.Thread(target=_monitor, daemon=True)
        monitor_thread.start()

        fire_concurrent(url, N, CANCEL_AFTER)
        time.sleep(POST_WAIT)

        monitor_done.wait(timeout=35)

        events = collect_logs(container, since)

        by_req: dict[str, list] = {}
        for e in events:
            by_req.setdefault(e.req, []).append(e)

        n_requests = len(by_req)
        n_detected = sum(
            1 for evts in by_req.values()
            if any(e.event == "disconnect_detected" for e in evts)
        )

        ghost_holdtime_ms = monitor_result.get("ghost_holdtime_ms")
        all_gone_ts = monitor_result.get("all_gone_ts_ms")

        db_cancel_latency_ms = None
        if all_gone_ts is not None and ghost_holdtime_ms is not None:
            if ghost_holdtime_ms < 2000:
                db_cancel_latency_ms = ghost_holdtime_ms

        db_cancelled = 1 if (ghost_holdtime_ms is not None and ghost_holdtime_ms < 2000) else 0

        detection_rate = round(n_detected / n_requests, 4) if n_requests else 0

        print(
            f"  run {run}/{runs}: det={n_detected}/{n_requests} "
            f"db_cancelled={db_cancelled} "
            f"ghost_holdtime={ghost_holdtime_ms}ms "
            f"db_cancel_latency={db_cancel_latency_ms}ms"
        )

        _write_csv(OUTPUT, E2A_FIELDS, {
            "framework":           framework,
            "N":                   N,
            "run_index":           run,
            "cancel_after_ms":     cancel_ms,
            "n_requests":          n_requests,
            "n_detected":          n_detected,
            "detection_rate":      detection_rate,
            "db_cancelled":        db_cancelled,
            "db_cancel_latency_ms": db_cancel_latency_ms,
            "ghost_holdtime_ms":   ghost_holdtime_ms,
        })

        if run < runs:
            time.sleep(SETTLE)


def main() -> None:
    parser = argparse.ArgumentParser(description="E2a data collection")
    parser.add_argument("--framework", required=True, choices=["aspnet", "webflux", "mvc"])
    parser.add_argument("--N",         required=True, type=int)
    parser.add_argument("--runs",      type=int, default=10)
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    run_cell(args.framework, args.N, args.runs)


if __name__ == "__main__":
    main()
