#!/usr/bin/env python3
"""Collects E2b streaming DB query cancellation data."""

import argparse
import re
import threading
import time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent))
from _common import (
    FRAMEWORKS, fire_concurrent, collect_logs,
    verify_clean_pg_stat, poll_pg_stat_activity,
    _write_csv, E2B_FIELDS,
)

REPO = Path(__file__).parent.parent.parent
OUTPUT_DIR = REPO / "experiments" / "sq2" / "e2b"
OUTPUT = OUTPUT_DIR / "e2b_stream.csv"

CANCEL_AFTER = 2.0
SETTLE = 5.0
POST_WAIT = 2.0

_ROWS_RE = re.compile(r"rows_consumed.*?count=(\d+)")


def run_cell(framework: str, N: int, runs: int) -> None:
    cfg = FRAMEWORKS[framework]
    url = f"{cfg['url']}/stream-db"
    container = cfg["container"]
    cancel_ms = int(CANCEL_AFTER * 1000)

    print(f"\nE2b | framework={framework} | N={N} | cancel_after={CANCEL_AFTER}s | runs={runs}")
    print("─" * 60)

    for run in range(1, runs + 1):
        verify_clean_pg_stat("n, pg_sleep")

        since = time.time()
        disconnect_ts = int((since + CANCEL_AFTER) * 1000)

        monitor_result: dict = {}
        monitor_done = threading.Event()

        def _monitor():
            monitor_result.update(
                poll_pg_stat_activity(disconnect_ts, "n, pg_sleep", timeout_s=90)
            )
            monitor_done.set()

        monitor_thread = threading.Thread(target=_monitor, daemon=True)
        monitor_thread.start()

        fire_concurrent(url, N, CANCEL_AFTER)
        time.sleep(POST_WAIT)

        monitor_done.wait(timeout=100)

        events = collect_logs(container, since)

        by_req: dict[str, list] = {}
        for e in events:
            by_req.setdefault(e.req, []).append(e)

        n_requests = len(by_req)
        n_detected = sum(
            1 for evts in by_req.values()
            if any(e.event == "disconnect_detected" for e in evts)
        )
        n_cursor_cancelled = sum(
            1 for evts in by_req.values()
            if any(e.event == "cancellation_detected" and
                   e.stage in ("db", "controller")
                   for e in evts)
        )

        rows_list = []
        for evts in by_req.values():
            rc_events = [e for e in evts if e.event == "rows_consumed" and e.detail]
            if rc_events:
                last_detail = rc_events[-1].detail
                m = _ROWS_RE.search(last_detail)
                if m:
                    rows_list.append(int(m.group(1)))

        rows_consumed_mean = round(sum(rows_list) / len(rows_list)) if rows_list else None
        ghost_holdtime_ms = monitor_result.get("ghost_holdtime_ms")
        detection_rate = round(n_detected / n_requests, 4) if n_requests else 0
        cursor_cancel_rate = round(n_cursor_cancelled / n_requests, 4) if n_requests else 0

        print(
            f"  run {run}/{runs}: det={n_detected}/{n_requests} "
            f"cursor_cancelled={n_cursor_cancelled}/{n_requests} "
            f"rows_consumed≈{rows_consumed_mean} "
            f"ghost_holdtime={ghost_holdtime_ms}ms"
        )

        _write_csv(OUTPUT, E2B_FIELDS, {
            "framework":       framework,
            "N":               N,
            "run_index":       run,
            "cancel_after_ms": cancel_ms,
            "n_requests":      n_requests,
            "n_detected":      n_detected,
            "detection_rate":  detection_rate,
            "cursor_cancelled": cursor_cancel_rate,
            "rows_consumed":   rows_consumed_mean,
            "ghost_holdtime_ms": ghost_holdtime_ms,
        })

        if run < runs:
            time.sleep(SETTLE)


def main() -> None:
    parser = argparse.ArgumentParser(description="E2b data collection")
    parser.add_argument("--framework", required=True, choices=["aspnet", "webflux"])
    parser.add_argument("--N",         required=True, type=int)
    parser.add_argument("--runs",      type=int, default=10)
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    run_cell(args.framework, args.N, args.runs)


if __name__ == "__main__":
    main()
