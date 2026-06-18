#!/usr/bin/env python3
"""Collects E2d outbound gRPC cancellation data."""

import argparse
import time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent))
from _common import (
    FRAMEWORKS, fire_concurrent, collect_logs,
    check_downstream_grpc_cancelled, _write_csv, E2D_FIELDS,
)

REPO = Path(__file__).parent.parent.parent
OUTPUT_DIR = REPO / "experiments" / "sq2" / "e2d"
OUTPUT = OUTPUT_DIR / "e2d_grpc.csv"

CANCEL_AFTER = 2.0
SETTLE = 3.0
POST_WAIT = 2.0


def run_cell(framework: str, N: int, runs: int) -> None:
    cfg = FRAMEWORKS[framework]
    url = f"{cfg['url']}/outbound-grpc"
    container = cfg["container"]
    cancel_ms = int(CANCEL_AFTER * 1000)

    print(f"\nE2d | framework={framework} | N={N} | cancel_after={CANCEL_AFTER}s | runs={runs}")
    print("─" * 60)

    for run in range(1, runs + 1):
        since = time.time()
        disconnect_ts = int((since + CANCEL_AFTER) * 1000)

        fire_concurrent(url, N, CANCEL_AFTER)
        time.sleep(POST_WAIT)

        events = collect_logs(container, since)
        downstream = check_downstream_grpc_cancelled(since, disconnect_ts, window_ms=5000)

        by_req: dict[str, list] = {}
        for e in events:
            by_req.setdefault(e.req, []).append(e)

        n_requests = len(by_req)
        n_detected = sum(
            1 for evts in by_req.values()
            if any(e.event == "disconnect_detected" for e in evts)
        )
        n_grpc_cancelled = sum(
            1 for evts in by_req.values()
            if any(e.event == "cancellation_detected" and
                   e.detail and "source=outbound_grpc" in e.detail
                   for e in evts)
        )

        latencies = []
        for evts in by_req.values():
            disc = [e for e in evts if e.event == "disconnect_detected"]
            cancel = [e for e in evts if e.event == "cancellation_detected"
                      and e.detail and "source=outbound_grpc" in e.detail]
            if disc and cancel:
                latencies.append(cancel[0].ts - disc[0].ts)

        lat_mean = round(sum(latencies) / len(latencies), 1) if latencies else None

        detection_rate = round(n_detected      / n_requests, 4) if n_requests else 0
        grpc_cancel_rate = round(n_grpc_cancelled / n_requests, 4) if n_requests else 0

        print(
            f"  run {run}/{runs}: det={n_detected}/{n_requests} "
            f"grpc_cancelled={n_grpc_cancelled}/{n_requests} "
            f"downstream={'✓' if downstream['confirmed'] else '✗'} "
            f"lat={downstream['latency_ms']}ms"
        )

        _write_csv(OUTPUT, E2D_FIELDS, {
            "framework":                       framework,
            "N":                               N,
            "run_index":                       run,
            "cancel_after_ms":                 cancel_ms,
            "n_requests":                      n_requests,
            "n_detected":                      n_detected,
            "detection_rate":                  detection_rate,
            "outbound_grpc_cancelled":         grpc_cancel_rate,
            "outbound_grpc_cancel_latency_ms": lat_mean,
            "downstream_grpc_confirmed":       1 if downstream["confirmed"] else 0,
            "downstream_grpc_confirm_latency_ms": downstream["latency_ms"],
        })

        if run < runs:
            time.sleep(SETTLE)


def main() -> None:
    parser = argparse.ArgumentParser(description="E2d data collection")
    parser.add_argument("--framework", required=True, choices=["aspnet", "webflux"])
    parser.add_argument("--N",         type=int, default=1)
    parser.add_argument("--runs",      type=int, default=10)
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    run_cell(args.framework, args.N, args.runs)


if __name__ == "__main__":
    main()
