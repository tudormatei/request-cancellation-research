#!/usr/bin/env python3
"""Collects per-layer cancellation handler timing relative to DB query completion."""

import argparse
import threading
import time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent))
from _common import (
    FRAMEWORKS, fire_concurrent, collect_logs,
    verify_clean_pg_stat, poll_pg_stat_activity,
    _write_csv,
)

REPO = Path(__file__).parent.parent.parent
OUTPUT_DIR = REPO / "experiments" / "sq2" / "e2_layer"
OUTPUT = OUTPUT_DIR / "e2_layer_timing.csv"

CANCEL_AFTER = 6.0
SETTLE = 8.0
POST_WAIT = 2.0

LAYER_EVENTS = {
    "webflux": [
        ("db",         "cancellation_detected",   "repository doOnCancel"),
        ("db",         "finally_cancel",          "repository doFinally"),
        ("service",    "cancellation_detected",   "service doOnCancel"),
        ("service",    "finally_cancel",          "service doFinally"),
        ("controller", "cancellation_propagated", "controller doOnCancel"),
    ],
    "aspnet": [
        ("service",    "cancellation_detected",   "service"),
        ("controller", "cancellation_propagated", "controller"),
    ],
}

FIELDS = [
    "framework", "run_index",
    "layer_stage", "layer_label",
    "handler_ts_ms",
    "db_gone_ts_ms",
    "gap_ms",
    "db_still_active",
]


def run_experiment(framework: str, runs: int) -> None:
    cfg = FRAMEWORKS[framework]
    url = f"{cfg['url']}/db"
    container = cfg["container"]
    layers = LAYER_EVENTS[framework]

    print(f"\nE2-layer | framework={framework} | N=1 | cancel_after={CANCEL_AFTER}s | runs={runs}")
    print("  Measuring: handler_ts - db_gone_ts per layer")
    print("  Negative gap = handler fired before DB stopped (notification)")
    print("  Positive gap = handler fired after  DB stopped (completion event)")
    print("─" * 70)

    for run in range(1, runs + 1):
        verify_clean_pg_stat("pg_sleep")

        since = time.time()
        disconnect_ts = int((since + CANCEL_AFTER) * 1000)

        monitor_result: dict = {}
        monitor_done = threading.Event()

        def _monitor():
            monitor_result.update(
                poll_pg_stat_activity(disconnect_ts, "pg_sleep", timeout_s=30)
            )
            monitor_done.set()

        threading.Thread(target=_monitor, daemon=True).start()

        fire_concurrent(url, 1, CANCEL_AFTER)
        time.sleep(POST_WAIT)
        monitor_done.wait(timeout=35)

        events = collect_logs(container, since)
        db_gone_ts = monitor_result.get("all_gone_ts_ms")

        by_req: dict[str, list] = {}
        for e in events:
            by_req.setdefault(e.req, []).append(e)

        print(f"  run {run}/{runs}: db_gone_ts={db_gone_ts}")

        for stage, event_name, label in layers:
            handler_ts = None
            for evts in by_req.values():
                for e in evts:
                    if e.stage == stage and e.event == event_name:
                        if handler_ts is None or e.ts < handler_ts:
                            handler_ts = e.ts

            gap_ms = None
            db_still_active = None
            if handler_ts is not None and db_gone_ts is not None:
                gap_ms = handler_ts - db_gone_ts
                db_still_active = 1 if gap_ms < 0 else 0

            print(
                f"    layer={label:<22} handler_ts={handler_ts}  "
                f"gap_ms={gap_ms}  db_still_active={db_still_active}"
            )

            _write_csv(OUTPUT, FIELDS, {
                "framework":       framework,
                "run_index":       run,
                "layer_stage":     stage,
                "layer_label":     label,
                "handler_ts_ms":   handler_ts,
                "db_gone_ts_ms":   db_gone_ts,
                "gap_ms":          gap_ms,
                "db_still_active": db_still_active,
            })

        if run < runs:
            time.sleep(SETTLE)

    print(f"\n  Output: {OUTPUT}")


def main() -> None:
    parser = argparse.ArgumentParser(description="E2-layer: multi-layer handler timing")
    parser.add_argument("--framework", required=True, choices=["aspnet", "webflux"])
    parser.add_argument("--runs",      type=int, default=10)
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    run_experiment(args.framework, args.runs)


if __name__ == "__main__":
    main()
