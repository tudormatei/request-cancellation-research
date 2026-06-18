#!/usr/bin/env python3
"""Collects E3 resource-occupancy data under sustained load."""

import argparse
import threading
import time
import http.client
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent))
from _common import (
    FRAMEWORKS, fire_concurrent, collect_logs,
    poll_pg_stat_activity, verify_clean_pg_stat,
    fire_sustained,
    _write_csv,
    E3A_FIELDS, E3C_FIELDS,
)

REPO = Path(__file__).parent.parent.parent
OUTPUT_DIR = REPO / "experiments" / "sq3"

PG_SLEEP_S = 10
CANCEL_AT_S = 6.0
GHOST_HOLDTIME_EXPECTED_MS = (PG_SLEEP_S - CANCEL_AT_S) * 1000



def run_e3a(framework: str, runs: int) -> None:
    out_dir = OUTPUT_DIR / "e3a"
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / "e3a_crosscheck.csv"

    fw_key = "spring-mvc" if framework == "mvc" else framework
    cfg = FRAMEWORKS[fw_key]
    url = f"{cfg['url']}/db"
    container = cfg["container"]
    N = 10

    print(f"\nE3a cross-check | framework={framework} | N={N} | cancel_at={CANCEL_AT_S}s | runs={runs}")
    print("─" * 60)

    for trial in range(1, runs + 1):
        verify_clean_pg_stat("pg_sleep")

        wave1_start = time.time()
        disconnect_ts = int((wave1_start + CANCEL_AT_S) * 1000)

        monitor_result: dict = {}
        monitor_done = threading.Event()

        def _monitor():
            monitor_result.update(
                poll_pg_stat_activity(disconnect_ts, "pg_sleep", timeout_s=30)
            )
            monitor_done.set()

        t = threading.Thread(target=_monitor, daemon=True)
        t.start()

        fire_concurrent(url, n=N, cancel_after=CANCEL_AT_S)

        monitor_done.wait(timeout=35)
        wave1_ghost_holdtime_ms = monitor_result.get("ghost_holdtime_ms")

        wave2_fire_ts = int(time.time() * 1000)
        wave2_delay_ms = wave2_fire_ts - disconnect_ts

        wave2_latencies: list[float] = []
        wave2_lock = threading.Lock()

        def _wave2_request():
            parsed_url = url
            host = cfg["url"].split("//")[1].split(":")[0]
            port = int(cfg["url"].split(":")[2].split("/")[0]) if ":" in cfg["url"].split("//")[1] else 80
            path = "/db"
            try:
                conn = http.client.HTTPConnection(host, port, timeout=30)
                conn.connect()
                t0 = time.time()
                conn.request("GET", path)
                resp = conn.getresponse()
                resp.read()
                conn.close()
                with wave2_lock:
                    wave2_latencies.append((time.time() - t0) * 1000)
            except Exception:
                pass

        threads = [threading.Thread(target=_wave2_request) for _ in range(N)]
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=35)

        wave2_success_rate = round(len(wave2_latencies) / N, 4)
        pool_wait_visible = 1 if any(lat > 500 for lat in wave2_latencies) else 0

        print(
            f"  trial {trial}/{runs}: ghost_holdtime={wave1_ghost_holdtime_ms}ms "
            f"wave2_delay={wave2_delay_ms}ms "
            f"wave2_success={wave2_success_rate} "
            f"pool_wait_visible={pool_wait_visible}"
        )

        _write_csv(output, E3A_FIELDS, {
            "framework":              framework,
            "trial":                  trial,
            "wave1_n":                N,
            "wave1_cancel_after_ms":  int(CANCEL_AT_S * 1000),
            "wave1_ghost_holdtime_ms": wave1_ghost_holdtime_ms,
            "wave2_delay_ms":         wave2_delay_ms,
            "wave2_success_rate":     wave2_success_rate,
            "pool_wait_visible":      pool_wait_visible,
        })

        if trial < runs:
            time.sleep(5.0)



def run_e3c(framework: str, X_rps: float, Y: float, duration_s: int,
            cancel_at_s: float = CANCEL_AT_S, label: str = "sustained") -> None:
    out_dir = OUTPUT_DIR / "e3c"
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / f"e3c_{label}.csv"

    fw_key = "spring-mvc" if framework == "mvc" else framework
    cfg = FRAMEWORKS[fw_key]
    url = f"{cfg['url']}/db"

    ghost_holdtime_s = PG_SLEEP_S - cancel_at_s
    print(f"\nE3c {label} | framework={framework} | X={X_rps}rps | Y={Y*100:.0f}% | "
          f"duration={duration_s}s | cancel_at={cancel_at_s}s")
    print("─" * 70)
    print(f"  WebFlux ghost_holdtime ≈ {ghost_holdtime_s:.1f}s (query runs to completion)")
    print(f"  Monitoring {duration_s}s in 30s windows …")
    print()

    windows = fire_sustained(
        url=url,
        rate_rps=X_rps,
        cancel_fraction=Y,
        cancel_after_s=cancel_at_s,
        duration_s=duration_s,
        window_s=30.0,
    )

    for w in windows:
        pct_failed = _pct(w["failed_fraction"])
        print(
            f"  window {w['window_index']:>2} [{w['window_start_s']:>3}–{w['window_end_s']:>3}s]  "
            f"sent={w['requests_sent']:>4}  "
            f"ok={w['succeeded']:>4}  "
            f"failed={w['failed']:>4} ({pct_failed}) [503={w['failed_503']} 500={w['failed_500']} to={w['failed_timeout']}]  "
            f"thru_ok={w['throughput_rps_succeeded']:.1f}rps  "
            f"p95={w['p95_latency_ms']}ms"
        )
        _write_csv(output, E3C_FIELDS, {
            "framework": framework,
            "X_rps":     X_rps,
            "Y_pct":     round(Y * 100, 1),
            **w,
        })


def _pct(v) -> str:
    if v is None:
        return "n/a"
    return f"{v * 100:.1f}%"



def main() -> None:
    parser = argparse.ArgumentParser(description="E3 data collection — resource occupancy (SQ3)")
    parser.add_argument("--mode",      required=True, choices=["e3a", "e3c"])
    parser.add_argument("--framework", choices=["aspnet", "webflux"],
                        help="Required for e3c; e3a runs both frameworks")
    parser.add_argument("--X",        type=float, help="Request rate in req/s (e3c only)")
    parser.add_argument("--Y",        type=float, default=0.10,
                        help="Cancel fraction 0–1 (e3c default 0.10)")
    parser.add_argument("--duration", type=int,   default=300,
                        help="Experiment duration in seconds (e3c default 300)")
    parser.add_argument("--cancel-at", type=float, default=CANCEL_AT_S,
                        help="Disconnect time in seconds into the query (e3c, default 6.0)")
    parser.add_argument("--label",    default="sustained",
                        help="Output file tag: e3c_<label>.csv (e3c only)")
    parser.add_argument("--runs",     type=int,   default=1,
                        help="Number of trials (e3a only, default 1)")
    args = parser.parse_args()

    if args.mode == "e3a":
        for fw in ["aspnet", "webflux"]:
            run_e3a(fw, args.runs)

    elif args.mode == "e3c":
        if not args.framework:
            parser.error("--framework required for e3c")
        if not args.X:
            parser.error("--X (request rate) required for e3c")
        run_e3c(args.framework, args.X, args.Y, args.duration,
                cancel_at_s=args.cancel_at, label=args.label)


if __name__ == "__main__":
    main()
