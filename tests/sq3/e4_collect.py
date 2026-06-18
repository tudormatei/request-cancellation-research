#!/usr/bin/env python3
"""Collects E4 ghost-write data across single-write and multi-step-write modes."""

import argparse
import http.client
import re
import time
import urllib.parse
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent))
from _common import (
    FRAMEWORKS, collect_logs, LOG_RE,
    _pg_exec, check_ghost_write, clear_ghost_writes,
    check_txn_steps, clear_txn_writes, count_idle_in_txn,
    _write_csv,
    E4A_FIELDS, E4B_FIELDS, E4B_TRANSITION_FIELDS, E4B_EXCEPTION_FIELDS, E4C_FIELDS,
)

REPO = Path(__file__).parent.parent.parent
OUTPUT_DIR = REPO / "experiments" / "sq3"

EXCEPTION_RE = re.compile(
    r"outer=(\S+)(?:\s+inner=(\S+))?(?:\s+sql_state=(\S+))?"
)


def parse_exception_detail(detail: str | None) -> dict:
    if not detail:
        return {"outer_exception_type": None, "inner_exception_type": None, "inner_sql_state": None}
    m = EXCEPTION_RE.search(detail)
    if not m:
        return {"outer_exception_type": None, "inner_exception_type": None, "inner_sql_state": None}
    return {
        "outer_exception_type": m.group(1),
        "inner_exception_type": m.group(2),
        "inner_sql_state":      m.group(3),
    }


def _send_and_cancel(base_url: str, path_with_query: str, cancel_after_s: float) -> None:
    """Send a single HTTP GET and close the connection after cancel_after_s seconds.

    Unlike fire_concurrent(), this preserves query parameters in the path.
    fire_concurrent() strips query strings via urlparse(..).path, which would
    drop the required ?D=<ms> parameter from ghost-write requests.
    """
    parsed = urllib.parse.urlparse(base_url)
    host = parsed.hostname
    port = parsed.port or 80
    try:
        conn = http.client.HTTPConnection(host, port, timeout=cancel_after_s + 30)
        conn.connect()
        conn.request("GET", path_with_query)
        deadline = time.time() + cancel_after_s
        remaining = deadline - time.time()
        if remaining > 0:
            time.sleep(remaining)
        conn.close()
    except Exception:
        pass


def _warmup(framework: str, n: int = 3, d_ms: int = 10) -> None:
    """Prime the connection pool with completing (un-cancelled) requests before
    measured trials. Removes the cold-start pre-dispatch artifact (first trial can
    miss because the pool connection is still being established when cancel fires)."""
    fw_key = "spring-mvc" if framework == "mvc" else framework
    parsed = urllib.parse.urlparse(FRAMEWORKS[fw_key]["url"])
    for _ in range(n):
        try:
            conn = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=30)
            conn.request("GET", f"/ghost-write?D={d_ms}")
            conn.getresponse().read()
            conn.close()
        except Exception:
            pass



def run_ghost_write_trial(
    framework: str,
    D_ms: int,
    cancel_at_s: float,
    settle_s: float = 3.0,
) -> dict:
    """
    Fire a single /ghost-write?D=<D_ms> request, cancel after cancel_at_s.
    Returns dict with ghost_write (bool) and exception chain fields.

    The /ghost-write endpoint must:
      1. Accept D query param (ms).
      2. Execute a simulated INSERT of duration D ms.
      3. Log req_id in structured log on request_received.
      4. Log exception detail on cancellation if an exception was raised.
    """
    fw_key = "spring-mvc" if framework == "mvc" else framework
    cfg = FRAMEWORKS[fw_key]
    container = cfg["container"]

    since = time.time()
    _send_and_cancel(cfg["url"], f"/ghost-write?D={D_ms}", cancel_at_s)
    time.sleep(2.0)

    events = collect_logs(container, since)

    req_id = None
    for e in events:
        if e.event == "request_received" and e.detail:
            m = re.search(r"req_id=([0-9a-f-]+)", e.detail)
            if m:
                req_id = m.group(1)

    detected = any(e.event == "disconnect_detected" for e in events)
    propagated = any(e.event == "cancellation_propagated" for e in events)
    log_success = any(e.event == "request_completed" for e in events)

    exc_detail = None
    for e in events:
        if e.event in ("cancellation_propagated", "exception_raised") and e.detail:
            exc_detail = e.detail
            break
    exc = parse_exception_detail(exc_detail)

    ghost_write = False
    if req_id:
        time.sleep(settle_s)
        ghost_write = check_ghost_write(req_id)

    return {
        "detected":       int(detected),
        "propagated":     int(propagated),
        "log_shows_success": int(log_success),
        "ghost_write":    int(ghost_write),
        **exc,
    }



STAGE3_DURATION_MS = 5000
E4A_CANCEL_AT_S = 3.0

def run_e4a(framework: str, runs: int) -> None:
    out_dir = OUTPUT_DIR / "e4a"
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / "e4a_log_audit.csv"

    print(f"\nE4a log audit | framework={framework} | runs={runs}")
    print("─" * 60)

    clear_ghost_writes()

    for trial in range(1, runs + 1):
        result = run_ghost_write_trial(framework, STAGE3_DURATION_MS, E4A_CANCEL_AT_S)

        print(
            f"  trial {trial}/{runs}: "
            f"detected={result['detected']} propagated={result['propagated']} "
            f"log_success={result['log_shows_success']} "
            f"ghost_write={result['ghost_write']} "
            f"outer={result['outer_exception_type']} inner={result['inner_exception_type']}"
        )

        _write_csv(output, E4A_FIELDS, {
            "framework":             framework,
            "trial":                 trial,
            "stage3_duration_ms":    STAGE3_DURATION_MS,
            "cancel_at_ms":          int(E4A_CANCEL_AT_S * 1000),
            "detected":              result["detected"],
            "propagated":            result["propagated"],
            "log_shows_success":     result["log_shows_success"],
            "ghost_write_confirmed": result["ghost_write"],
            "outer_exception_type":  result["outer_exception_type"],
            "inner_exception_type":  result["inner_exception_type"],
            "inner_sql_state":       result["inner_sql_state"],
        })

        time.sleep(1.0)



E4B_CANCEL_AT_S = 0.05

D_ASPNET = [50, 75, 100, 125, 150, 175, 200, 250, 500, 1000]
D_WEBFLUX = [100, 250, 1000]


def run_e4b(framework: str, D_ms: int, runs: int) -> None:
    out_dir = OUTPUT_DIR / "e4b"
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / "e4b_dsweep.csv"

    print(f"\nE4b D-sweep | framework={framework} | D={D_ms}ms | runs={runs}")
    print("─" * 60)

    _warmup(framework)
    for trial in range(1, runs + 1):
        clear_ghost_writes()
        result = run_ghost_write_trial(framework, D_ms, E4B_CANCEL_AT_S)

        print(
            f"  trial {trial}/{runs}: ghost={result['ghost_write']} "
            f"outer={result['outer_exception_type']} inner={result['inner_exception_type']} "
            f"sql_state={result['inner_sql_state']}"
        )

        _write_csv(output, E4B_FIELDS, {
            "framework": framework,
            "D_ms":      D_ms,
            "trial":     trial,
            **{k: result[k] for k in ("ghost_write", "outer_exception_type",
                                       "inner_exception_type", "inner_sql_state")},
        })

        time.sleep(0.5)



def run_e4b_transition(D_ms: int, runs: int, cancel_at_s: float = E4B_CANCEL_AT_S) -> None:
    out_dir = OUTPUT_DIR / "e4b"
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = ("e4b_transition.csv" if abs(cancel_at_s - 0.05) < 1e-9
             else f"e4b_transition_cancelat{int(round(cancel_at_s * 1000))}.csv")
    output = out_dir / fname

    print(f"\nE4b transition | aspnet | D={D_ms}ms | cancel_at={int(cancel_at_s*1000)}ms | runs={runs}")
    print("─" * 60)

    _warmup("aspnet")
    ghost_count = 0
    for trial in range(1, runs + 1):
        clear_ghost_writes()
        result = run_ghost_write_trial("aspnet", D_ms, cancel_at_s)
        ghost_count += result["ghost_write"]

        print(f"  trial {trial}/{runs}: ghost={result['ghost_write']}  (cumulative: {ghost_count}/{trial})")

        _write_csv(output, E4B_TRANSITION_FIELDS, {
            "framework": "aspnet",
            "D_ms":      D_ms,
            "trial":     trial,
            "ghost_write": result["ghost_write"],
        })

        time.sleep(0.5)



def run_e4b_exceptions(D_ms: int, D_category: str, runs: int) -> None:
    out_dir = OUTPUT_DIR / "e4b"
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / "e4b_exceptions.csv"

    print(f"\nE4b exceptions | aspnet | D={D_ms}ms | category={D_category} | runs={runs}")
    print("─" * 60)

    for trial in range(1, runs + 1):
        clear_ghost_writes()
        result = run_ghost_write_trial("aspnet", D_ms, E4B_CANCEL_AT_S)

        print(
            f"  trial {trial}/{runs}: ghost={result['ghost_write']} "
            f"outer={result['outer_exception_type']} inner={result['inner_exception_type']} "
            f"sql_state={result['inner_sql_state']}"
        )

        _write_csv(output, E4B_EXCEPTION_FIELDS, {
            "framework":  "aspnet",
            "D_category": D_category,
            "D_ms":       D_ms,
            "trial":      trial,
            **{k: result[k] for k in ("ghost_write", "outer_exception_type",
                                       "inner_exception_type", "inner_sql_state")},
        })

        time.sleep(0.5)



E4C_GAP_MS = 2000
E4C_CANCEL_AT_S = 0.5

def run_e4c(framework: str, tx_mode: bool, runs: int) -> None:
    out_dir = OUTPUT_DIR / "e4c"
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / "e4c_state.csv"

    fw_key = "spring-mvc" if framework == "mvc" else framework
    cfg = FRAMEWORKS[fw_key]
    container = cfg["container"]
    tx_q = "true" if tx_mode else "false"

    print(f"\nE4c multi-step state | framework={framework} | tx={tx_mode} | runs={runs}")
    print("─" * 60)

    _warmup(framework)
    counts = {"rollback": 0, "torn": 0, "full": 0, "unknown": 0}
    for trial in range(1, runs + 1):
        clear_txn_writes()
        since = time.time()
        _send_and_cancel(cfg["url"], f"/txn-write?gap={E4C_GAP_MS}&tx={tx_q}", E4C_CANCEL_AT_S)

        time.sleep(1.0)
        idle_after = count_idle_in_txn()
        time.sleep(3.0)

        events = collect_logs(container, since)
        req_id = None
        for e in events:
            if e.event == "request_received" and e.detail:
                m = re.search(r"req_id=([0-9a-f-]+)", e.detail)
                if m:
                    req_id = m.group(1)
        committed = check_txn_steps(req_id) if req_id else -1
        outcome = {0: "rollback", 1: "torn", 2: "full"}.get(committed, "unknown")
        counts[outcome] += 1

        detected = any(e.event in ("disconnect_detected", "client_disconnected",
                                      "cancellation_detected") for e in events)
        propagated = any(e.event == "cancellation_propagated" for e in events)

        print(f"  trial {trial}/{runs}: committed_steps={committed} outcome={outcome} "
              f"idle_in_txn={idle_after} detected={int(detected)} propagated={int(propagated)}")

        _write_csv(output, E4C_FIELDS, {
            "framework":        framework,
            "tx_mode":          tx_q,
            "trial":            trial,
            "gap_ms":           E4C_GAP_MS,
            "cancel_at_ms":     int(E4C_CANCEL_AT_S * 1000),
            "committed_steps":  committed,
            "outcome":          outcome,
            "idle_in_txn_after": idle_after,
            "detected":         int(detected),
            "propagated":       int(propagated),
        })
        time.sleep(0.5)

    print(f"  → {dict(counts)}")



def main() -> None:
    parser = argparse.ArgumentParser(description="E4 data collection — ghost writes (SQ3)")
    parser.add_argument("--mode", required=True,
                        choices=["e4a", "e4b", "e4b-transition", "e4b-exceptions", "e4c"])
    parser.add_argument("--framework", choices=["aspnet", "webflux", "mvc"],
                        help="Required for e4b; e4a runs all three or a single fw; transition/exceptions use aspnet")
    parser.add_argument("--D",      type=int, help="INSERT duration in ms (e4b / transition / exceptions)")
    parser.add_argument("--D-star", type=int, dest="D_star",
                        help="D* value in ms (required for e4b-transition and e4b-exceptions)")
    parser.add_argument("--runs",   type=int, default=None,
                        help="Trial count (default: 20 for e4a/e4b, 50 for transition, 10 for exceptions)")
    parser.add_argument("--cancel-at", type=float, default=None, dest="cancel_at",
                        help="Cancel timing in seconds (default 0.05 for e4b-transition; non-default writes a cancel_at-suffixed CSV)")
    parser.add_argument("--tx", choices=["true", "false"], default=None,
                        help="e4c transaction mode; if omitted runs both")
    args = parser.parse_args()

    if args.mode == "e4a":
        runs = args.runs or 20
        frameworks = [args.framework] if args.framework else ["aspnet", "webflux", "mvc"]
        for fw in frameworks:
            run_e4a(fw, runs)

    elif args.mode == "e4b":
        if not args.framework:
            parser.error("--framework required for e4b")
        D_values = D_ASPNET if args.framework == "aspnet" else D_WEBFLUX
        if args.D:
            D_values = [args.D]
        runs = args.runs or (20 if args.framework == "aspnet" else 10)
        for D in D_values:
            run_e4b(args.framework, D, runs)

    elif args.mode == "e4b-transition":
        if not args.D_star and not args.D:
            parser.error("--D-star or --D required for e4b-transition")
        cancel_at = args.cancel_at if args.cancel_at is not None else E4B_CANCEL_AT_S
        if args.D:
            run_e4b_transition(args.D, args.runs or 50, cancel_at)
        else:
            dstar = args.D_star
            for D in [dstar - 50, dstar - 25, dstar, dstar + 25, dstar + 50]:
                run_e4b_transition(D, args.runs or 50, cancel_at)

    elif args.mode == "e4b-exceptions":
        if not args.D_star and not args.D:
            parser.error("--D-star or --D required for e4b-exceptions")
        if args.D:
            category = "below_dstar" if args.D < (args.D_star or args.D) else "above_dstar"
            run_e4b_exceptions(args.D, category, args.runs or 10)
        else:
            dstar = args.D_star
            run_e4b_exceptions(dstar - 50, "below_dstar", args.runs or 10)
            run_e4b_exceptions(dstar + 50, "above_dstar", args.runs or 10)

    elif args.mode == "e4c":
        if not args.framework:
            parser.error("--framework required for e4c")
        runs = args.runs or 20
        tx_modes = [args.tx == "true"] if args.tx else [False, True]
        for tx in tx_modes:
            run_e4c(args.framework, tx, runs)


if __name__ == "__main__":
    main()
