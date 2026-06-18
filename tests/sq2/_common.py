"""Shared infrastructure for SQ2 (IO Cancellation Protocol Study) data collection."""

import importlib.util
import re
import subprocess
import threading
import time
import sys
from pathlib import Path
from typing import Optional

_SQ1_PATH = Path(__file__).parent.parent / "sq1" / "_common.py"
_spec = importlib.util.spec_from_file_location("sq1_common", _SQ1_PATH)
_sq1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sq1)

FRAMEWORKS = _sq1.FRAMEWORKS
fire_concurrent = _sq1.fire_concurrent
collect_logs = _sq1.collect_logs
LOG_RE = _sq1.LOG_RE


PG_HOST = "localhost"
PG_PORT = 5432
PG_DB = "thesisdb"
PG_USER = "thesisuser"
PG_PASS = "thesispass"


def _pg_exec(sql: str, params: tuple = ()) -> list:
    """Execute a query via docker exec psql to avoid psycopg3 install requirement."""
    cmd = [
        "docker", "exec", "thesis_postgres",
        "psql", "-U", PG_USER, "-d", PG_DB,
        "-t", "-A", "-F", "\t",
        "-c", sql,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    rows = [r.strip() for r in result.stdout.strip().splitlines() if r.strip()]
    return rows


def count_active_pg_sleep() -> int:
    """Count rows in pg_stat_activity with active pg_sleep queries."""
    rows = _pg_exec(
        "SELECT count(*) FROM pg_stat_activity "
        "WHERE query LIKE 'SELECT pg_sleep%' AND state = 'active'"
    )
    return int(rows[0]) if rows else 0


def count_active_stream_queries() -> int:
    """Count rows in pg_stat_activity with active generate_series queries."""
    rows = _pg_exec(
        "SELECT count(*) FROM pg_stat_activity "
        "WHERE query LIKE 'SELECT generate_series%' AND state = 'active'"
    )
    return int(rows[0]) if rows else 0


def verify_clean_pg_stat(query_filter: str = "pg_sleep", timeout_s: float = 15) -> None:
    """Block until no active queries matching filter exist in pg_stat_activity."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        rows = _pg_exec(
            f"SELECT count(*) FROM pg_stat_activity "
            f"WHERE query LIKE 'SELECT {query_filter}%' AND state = 'active'"
        )
        count = int(rows[0]) if rows else 0
        if count == 0:
            return
        time.sleep(0.2)
    print(f"  ⚠ pg_stat_activity not clean after {timeout_s}s ({query_filter})")


def poll_pg_stat_activity(
    disconnect_ts_ms: int,
    query_filter: str = "pg_sleep",
    poll_interval_s: float = 0.1,
    timeout_s: float = 30,
) -> dict:
    """
    Poll pg_stat_activity every poll_interval_s until active queries matching
    query_filter disappear or timeout is reached.

    Returns dict with:
      all_gone_ts_ms:  unix_ms when count first dropped to 0 (None if timeout)
      ghost_holdtime_ms: ms from disconnect_ts_ms to all_gone_ts_ms
    """
    deadline_appear = time.time() + 5
    while time.time() < deadline_appear:
        rows = _pg_exec(
            f"SELECT count(*) FROM pg_stat_activity "
            f"WHERE query LIKE 'SELECT {query_filter}%' AND state = 'active'"
        )
        if rows and int(rows[0]) > 0:
            break
        time.sleep(poll_interval_s)

    all_gone_ts_ms: Optional[int] = None
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        rows = _pg_exec(
            f"SELECT count(*) FROM pg_stat_activity "
            f"WHERE query LIKE 'SELECT {query_filter}%' AND state = 'active'"
        )
        count = int(rows[0]) if rows else 0
        if count == 0:
            all_gone_ts_ms = int(time.time() * 1000)
            break
        time.sleep(poll_interval_s)

    ghost_holdtime_ms: Optional[float] = None
    if all_gone_ts_ms is not None:
        ghost_holdtime_ms = max(0, all_gone_ts_ms - disconnect_ts_ms)

    return {
        "all_gone_ts_ms":   all_gone_ts_ms,
        "ghost_holdtime_ms": ghost_holdtime_ms,
    }



DOWNSTREAM_CONTAINER = "thesis_downstream"

DOWNSTREAM_LOG_RE = re.compile(
    r"ts=(\d+)\s+req=(\S+)\s+stage=downstream\s+event=(\S+)(?:\s+detail=(.+))?"
)


def collect_downstream_events(since_unix: float) -> list[dict]:
    """
    Return list of downstream log events since `since_unix` timestamp.
    Each event is a dict with keys: ts, req, event, detail.
    """
    result = subprocess.run(
        ["docker", "logs", "--since", str(int(since_unix)), DOWNSTREAM_CONTAINER],
        capture_output=True, text=True,
    )
    events = []
    for line in (result.stdout + result.stderr).splitlines():
        m = DOWNSTREAM_LOG_RE.search(line)
        if m:
            events.append({
                "ts":     int(m.group(1)),
                "req":    m.group(2),
                "event":  m.group(3),
                "detail": m.group(4),
            })
    return events


def check_downstream_cancelled(
    since_unix: float,
    disconnect_ts_ms: int,
    window_ms: float = 5000,
) -> dict:
    """
    Check if the downstream mock logged connection_closed events after the disconnect.
    Returns dict with:
      confirmed: bool — at least one connection_closed event within window_ms of disconnect
      latency_ms: time from disconnect_ts_ms to first connection_closed (None if unconfirmed)
    """
    events = collect_downstream_events(since_unix)
    close_events = [
        e for e in events
        if e["event"] == "connection_closed"
        and e["ts"] >= disconnect_ts_ms
        and e["ts"] <= disconnect_ts_ms + window_ms
    ]
    if not close_events:
        return {"confirmed": False, "latency_ms": None}

    first_ts = min(e["ts"] for e in close_events)
    return {
        "confirmed":  True,
        "latency_ms": max(0, first_ts - disconnect_ts_ms),
    }



import csv
import statistics
from typing import Any

E2A_FIELDS = [
    "framework", "N", "run_index", "cancel_after_ms",
    "n_requests", "n_detected", "detection_rate",
    "db_cancelled", "db_cancel_latency_ms", "ghost_holdtime_ms",
]

E2B_FIELDS = [
    "framework", "N", "run_index", "cancel_after_ms",
    "n_requests", "n_detected", "detection_rate",
    "cursor_cancelled", "rows_consumed", "ghost_holdtime_ms",
]

E2C_FIELDS = [
    "framework", "N", "run_index", "cancel_after_ms",
    "n_requests", "n_detected", "detection_rate",
    "outbound_cancelled", "outbound_cancel_latency_ms",
    "downstream_confirmed", "downstream_confirm_latency_ms",
]

E2D_FIELDS = [
    "framework", "N", "run_index", "cancel_after_ms",
    "n_requests", "n_detected", "detection_rate",
    "outbound_grpc_cancelled", "outbound_grpc_cancel_latency_ms",
    "downstream_grpc_confirmed", "downstream_grpc_confirm_latency_ms",
]


def check_downstream_grpc_cancelled(
    since_unix: float,
    disconnect_ts_ms: int,
    window_ms: float = 5000,
) -> dict:
    """
    Check if the downstream mock logged grpc_call_cancelled events after the disconnect.
    Returns dict with confirmed bool and latency_ms from disconnect to first cancel event.
    """
    events = collect_downstream_events(since_unix)
    cancel_events = [
        e for e in events
        if e["event"] == "grpc_call_cancelled"
        and e["ts"] >= disconnect_ts_ms
        and e["ts"] <= disconnect_ts_ms + window_ms
    ]
    if not cancel_events:
        return {"confirmed": False, "latency_ms": None}

    first_ts = min(e["ts"] for e in cancel_events)
    return {
        "confirmed":  True,
        "latency_ms": max(0, first_ts - disconnect_ts_ms),
    }


def _write_csv(path: Path, fields: list[str], row: dict) -> None:
    exists = path.exists()
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerow(row)
