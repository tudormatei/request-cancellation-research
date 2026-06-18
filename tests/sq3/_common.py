"""Shared infrastructure for SQ3 (Behavioural and Operational Consequences) data collection."""

import importlib.util
import statistics
import threading
import time
import http.client
import urllib.parse
from pathlib import Path
from typing import Optional

_SQ2_PATH = Path(__file__).parent.parent / "sq2" / "_common.py"
_spec = importlib.util.spec_from_file_location("sq2_common", _SQ2_PATH)
_sq2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sq2)

FRAMEWORKS = _sq2.FRAMEWORKS
fire_concurrent = _sq2.fire_concurrent
collect_logs = _sq2.collect_logs
LOG_RE = _sq2.LOG_RE
_pg_exec = _sq2._pg_exec
poll_pg_stat_activity = _sq2.poll_pg_stat_activity
verify_clean_pg_stat = _sq2.verify_clean_pg_stat
_write_csv = _sq2._write_csv



def check_ghost_write(req_id: str) -> bool:
    """Return True if an INSERT with req_id was committed to the ghost_writes table."""
    rows = _pg_exec(
        f"SELECT count(*) FROM ghost_writes WHERE req_id = '{req_id}'"
    )
    return int(rows[0]) > 0 if rows else False


def clear_ghost_writes() -> None:
    """Delete all rows from ghost_writes table (between trials)."""
    _pg_exec("DELETE FROM ghost_writes")



def check_txn_steps(req_id: str) -> int:
    """Return how many of the two steps committed for req_id (0, 1, or 2).
    0 = clean rollback, 1 = TORN/partial write, 2 = full write."""
    rows = _pg_exec(f"SELECT count(*) FROM txn_writes WHERE req_id = '{req_id}'")
    return int(rows[0]) if rows else 0


def clear_txn_writes() -> None:
    """Delete all rows from txn_writes table (between trials)."""
    _pg_exec("DELETE FROM txn_writes")


def count_idle_in_txn() -> int:
    """Count Postgres backends sitting 'idle in transaction' (a dangling/leaked
    transaction holding locks). Used after a transactional cancel to test whether the
    framework rolled back cleanly or left the transaction open."""
    rows = _pg_exec(
        "SELECT count(*) FROM pg_stat_activity "
        "WHERE datname='thesisdb' AND state='idle in transaction'"
    )
    return int(rows[0]) if rows else 0



def fire_sustained(
    url: str,
    rate_rps: float,
    cancel_fraction: float,
    cancel_after_s: float,
    duration_s: float,
    window_s: float = 30.0,
) -> list[dict]:
    """
    Fire requests at rate_rps for duration_s seconds.
    cancel_fraction of requests are cancelled after cancel_after_s.
    The remainder complete naturally (connection left open until response).

    Returns list of per-window measurement dicts (one per window_s interval) with keys:
      window_index, window_start_s, window_end_s,
      requests_sent, completed, cancelled, pool_exhausted,
      pool_exhausted_fraction, throughput_rps_actual,
      p95_latency_ms, p99_latency_ms
    """
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname
    port = parsed.port or 80
    path = parsed.path
    if parsed.query:
        path = f"{path}?{parsed.query}"

    interval_s = 1.0 / rate_rps

    lock = threading.Lock()
    results: list[dict] = []
    stop_event = threading.Event()

    def send_request(is_cancel: bool, req_start: float) -> None:
        try:
            conn = http.client.HTTPConnection(host, port, timeout=cancel_after_s + 30)
            conn.connect()
            conn.request("GET", path)
            if is_cancel:
                deadline = req_start + cancel_after_s
                wait = deadline - time.time()
                if wait > 0:
                    time.sleep(wait)
                conn.close()
                latency_ms = (time.time() - req_start) * 1000
                with lock:
                    results.append({
                        "start_s": req_start, "latency_ms": latency_ms,
                        "status": 0, "cancelled": True,
                        "succeeded": False, "failed": False,
                    })
            else:
                resp = conn.getresponse()
                resp.read()
                latency_ms = (time.time() - req_start) * 1000
                status = resp.status
                with lock:
                    results.append({
                        "start_s": req_start, "latency_ms": latency_ms,
                        "status": status, "cancelled": False,
                        "succeeded": status == 200, "failed": status != 200,
                    })
                conn.close()
        except OSError:
            latency_ms = (time.time() - req_start) * 1000
            with lock:
                results.append({
                    "start_s": req_start, "latency_ms": latency_ms,
                    "status": -1, "cancelled": False,
                    "succeeded": False, "failed": True,
                })

    experiment_start = time.time()
    req_counter = 0
    active_threads: list[threading.Thread] = []

    while time.time() - experiment_start < duration_s:
        req_start = time.time()
        is_cancel = (cancel_fraction > 0 and
                     int((req_counter + 1) * cancel_fraction) > int(req_counter * cancel_fraction))
        t = threading.Thread(target=send_request, args=(is_cancel, req_start), daemon=True)
        t.start()
        active_threads.append(t)
        req_counter += 1

        elapsed = time.time() - req_start
        sleep_time = interval_s - elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)

    settle_deadline = time.time() + cancel_after_s + 5
    for t in active_threads:
        remaining = max(0, settle_deadline - time.time())
        t.join(timeout=remaining)

    n_windows = int(duration_s / window_s)
    windows = []
    for w in range(n_windows):
        w_start = w * window_s
        w_end = (w + 1) * window_s
        in_window = [r for r in results if w_start <= r["start_s"] - experiment_start < w_end]

        n_sent = len(in_window)
        n_cancelled = sum(1 for r in in_window if r["cancelled"])
        n_succeeded = sum(1 for r in in_window if r["succeeded"])
        n_failed = sum(1 for r in in_window if r["failed"])
        n_failed_503 = sum(1 for r in in_window if r["status"] == 503)
        n_failed_500 = sum(1 for r in in_window if r["failed"] and r["status"] >= 500 and r["status"] != 503)
        n_failed_timeout = sum(1 for r in in_window if r["status"] == -1)
        n_failed_other = n_failed - n_failed_503 - n_failed_500 - n_failed_timeout

        latencies = [r["latency_ms"] for r in in_window if not r["cancelled"]]
        latencies_sorted = sorted(latencies)
        p95 = latencies_sorted[int(len(latencies_sorted) * 0.95)] if latencies_sorted else None
        p99 = latencies_sorted[int(len(latencies_sorted) * 0.99)] if latencies_sorted else None

        n_attempted = n_sent - n_cancelled
        failed_fraction = round(n_failed / n_attempted, 4) if n_attempted > 0 else 0.0
        throughput_succeeded = round(n_succeeded / window_s, 3)

        windows.append({
            "window_index":            w,
            "window_start_s":          w_start,
            "window_end_s":            w_end,
            "requests_sent":           n_sent,
            "cancelled":               n_cancelled,
            "succeeded":               n_succeeded,
            "failed":                  n_failed,
            "failed_fraction":         failed_fraction,
            "failed_503":              n_failed_503,
            "failed_500":              n_failed_500,
            "failed_timeout":          n_failed_timeout,
            "failed_other":            n_failed_other,
            "throughput_rps_succeeded": throughput_succeeded,
            "p95_latency_ms":          round(p95, 1) if p95 is not None else None,
            "p99_latency_ms":          round(p99, 1) if p99 is not None else None,
        })

    return windows



E3A_FIELDS = [
    "framework", "trial", "wave1_n", "wave1_cancel_after_ms",
    "wave1_ghost_holdtime_ms", "wave2_delay_ms", "wave2_success_rate", "pool_wait_visible",
]

E3C_FIELDS = [
    "framework", "X_rps", "Y_pct", "window_index",
    "window_start_s", "window_end_s",
    "requests_sent", "cancelled", "succeeded", "failed", "failed_fraction",
    "failed_503", "failed_500", "failed_timeout", "failed_other",
    "throughput_rps_succeeded", "p95_latency_ms", "p99_latency_ms",
]

E4A_FIELDS = [
    "framework", "trial", "stage3_duration_ms", "cancel_at_ms",
    "detected", "propagated", "log_shows_success", "ghost_write_confirmed",
    "outer_exception_type", "inner_exception_type", "inner_sql_state",
]

E4B_FIELDS = [
    "framework", "D_ms", "trial",
    "ghost_write", "outer_exception_type", "inner_exception_type", "inner_sql_state",
]

E4B_TRANSITION_FIELDS = [
    "framework", "D_ms", "trial", "ghost_write",
]

E4C_FIELDS = [
    "framework", "tx_mode", "trial", "gap_ms", "cancel_at_ms",
    "committed_steps", "outcome", "idle_in_txn_after", "detected", "propagated",
]

E4B_EXCEPTION_FIELDS = [
    "framework", "D_category", "D_ms", "trial",
    "ghost_write", "outer_exception_type", "inner_exception_type", "inner_sql_state",
]
