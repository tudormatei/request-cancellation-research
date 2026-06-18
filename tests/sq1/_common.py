"""Shared infrastructure for SQ1 data collection scripts."""

import csv
import http.client
import re
import statistics
import subprocess
import threading
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

FRAMEWORKS = {
    "aspnet":     {"url": "http://localhost:8081", "container": "thesis_aspnet"},
    "webflux":    {"url": "http://localhost:8083", "container": "thesis_spring_webflux"},
    "spring-mvc": {"url": "http://localhost:8082", "container": "thesis_spring_mvc"},
    "go":         {"url": "http://localhost:8084", "container": "thesis_go_service"},
}

SCENARIO_DURATION_MS = {
    "cpu":   15_000,
    "async": 10_000,
}

POST_WAIT = {
    "aspnet":     2,
    "webflux":    2,
    "spring-mvc": 11,
    "go":         2,
}

LOG_RE = re.compile(
    r"ts=(\d+)\s+req=(\S+)\s+stage=(\S+)\s+event=(\S+)(?:\s+detail=(.+))?"
)
CANCEL_EVENTS = {"cancellation_detected", "cancellation_propagated"}

SUMMARY_FIELDS = [
    "framework", "scenario", "N", "T", "yield_interval_ms", "cancel_after_ms",
    "cores", "cpu_duration_s",
    "n_requests", "n_cancelled", "cancel_rate",
    "L1_mean", "L1_sd", "L1_median", "L1_min", "L1_max",
    "L2_mean", "L2_sd", "L2_median", "L2_min", "L2_max",
    "waste_mean", "waste_sd", "waste_median", "waste_min", "waste_max",
]

PER_RUN_FIELDS = [
    "framework", "scenario", "N", "T", "yield_interval_ms", "run_index",
    "n_requests", "n_cancelled", "run_cancel_rate",
    "L1_mean", "L1_sd", "L1_median", "L1_min", "L1_max",
]


@dataclass
class Event:
    ts: int
    req: str
    stage: str
    event: str
    detail: Optional[str] = None


@dataclass
class RequestMetrics:
    framework: str
    run: int
    req: str
    received_ts: int
    client_ts: Optional[int]
    cancel_after_ms: int
    scenario: str
    last_event_ts: int
    cancelled: bool
    actual_disconnect_ts: Optional[int]

    @property
    def estimated_disconnect_ts(self) -> int:
        return self.client_ts if self.client_ts is not None else self.received_ts + self.cancel_after_ms

    @property
    def detection_latency_ms(self) -> Optional[float]:
        if self.actual_disconnect_ts is None:
            return None
        return self.actual_disconnect_ts - self.estimated_disconnect_ts

    @property
    def propagation_ms(self) -> Optional[float]:
        if self.actual_disconnect_ts is None:
            return None
        return self.last_event_ts - self.actual_disconnect_ts

    @property
    def waste_ratio(self) -> Optional[float]:
        remaining = SCENARIO_DURATION_MS.get(self.scenario, 0) - self.cancel_after_ms
        if remaining <= 0 or self.propagation_ms is None:
            return None
        return max(0.0, self.propagation_ms) / remaining


def _stat(vals: list[float]) -> dict:
    if not vals:
        return {k: "" for k in ("mean", "sd", "median", "min", "max")}
    n = len(vals)
    return {
        "mean":   round(statistics.mean(vals), 3),
        "sd":     round(statistics.stdev(vals), 3) if n >= 2 else 0.0,
        "median": round(statistics.median(vals), 3),
        "min":    round(min(vals), 3),
        "max":    round(max(vals), 3),
    }


def compute_summary_row(metrics: list, framework: str, scenario: str,
                        N: int, T: int, cancel_after_ms: int,
                        yield_interval_ms: int | None = None,
                        cores: int | None = None,
                        cpu_duration_s: int | None = None) -> dict:
    cancelled = [m for m in metrics if m.cancelled]
    n_total, n_cancel = len(metrics), len(cancelled)
    l1 = _stat([m.detection_latency_ms for m in cancelled if m.detection_latency_ms is not None])
    l2 = _stat([m.propagation_ms       for m in cancelled if m.propagation_ms       is not None])
    wr = _stat([m.waste_ratio           for m in cancelled if m.waste_ratio           is not None])
    return {
        "framework": framework, "scenario": scenario, "N": N, "T": T,
        "yield_interval_ms": yield_interval_ms, "cancel_after_ms": cancel_after_ms,
        "cores": cores, "cpu_duration_s": cpu_duration_s,
        "n_requests": n_total, "n_cancelled": n_cancel,
        "cancel_rate": round(n_cancel / n_total, 4) if n_total else "",
        "L1_mean": l1["mean"], "L1_sd": l1["sd"], "L1_median": l1["median"],
        "L1_min":  l1["min"],  "L1_max": l1["max"],
        "L2_mean": l2["mean"], "L2_sd": l2["sd"], "L2_median": l2["median"],
        "L2_min":  l2["min"],  "L2_max": l2["max"],
        "waste_mean": wr["mean"], "waste_sd": wr["sd"], "waste_median": wr["median"],
        "waste_min":  wr["min"],  "waste_max": wr["max"],
    }


def write_summary_csv(csv_path: Path, rows: list[dict]) -> None:
    exists = csv_path.exists()
    with csv_path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerows(rows)


def write_per_run_csv(csv_path: Path, row: dict) -> None:
    exists = csv_path.exists()
    with csv_path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PER_RUN_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def fire_concurrent(url: str, n: int, cancel_after: float) -> None:
    parsed = urllib.parse.urlparse(url)
    host, port, path = parsed.hostname, parsed.port or 80, parsed.path
    barrier = threading.Barrier(n)

    def send():
        try:
            conn = http.client.HTTPConnection(host, port, timeout=cancel_after + 10)
            conn.connect()
            barrier.wait()
            planned_ts = int(time.time() * 1000) + int(cancel_after * 1000)
            conn.request("GET", f"{path}?ts={planned_ts}")
            time.sleep(max(0.0, planned_ts / 1000 - time.time()))
            conn.close()
        except Exception:
            pass

    threads = [threading.Thread(target=send) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def collect_logs(container: str, since_unix: float) -> list[Event]:
    result = subprocess.run(
        ["docker", "logs", "--since", str(int(since_unix)), container],
        capture_output=True, text=True,
    )
    events = []
    for line in (result.stdout + result.stderr).splitlines():
        m = LOG_RE.search(line)
        if m:
            events.append(Event(ts=int(m.group(1)), req=m.group(2),
                                stage=m.group(3), event=m.group(4), detail=m.group(5)))
    return events


def parse_metrics(events: list[Event], framework: str, run: int,
                  scenario: str, cancel_after_ms: int) -> list[RequestMetrics]:
    by_req: dict[str, list[Event]] = {}
    for e in events:
        by_req.setdefault(e.req, []).append(e)
    results = []
    for req, evts in by_req.items():
        evts = sorted(evts, key=lambda e: e.ts)
        recv = next((e for e in evts if e.event == "request_received"), None)
        if recv is None:
            continue
        client_ts = None
        if recv.detail:
            m = re.search(r'client_ts=(\d+)', recv.detail)
            if m:
                client_ts = int(m.group(1))
        results.append(RequestMetrics(
            framework=framework, run=run, req=req,
            received_ts=recv.ts, client_ts=client_ts,
            cancel_after_ms=cancel_after_ms, scenario=scenario,
            last_event_ts=evts[-1].ts,
            cancelled=bool([e for e in evts if e.event in CANCEL_EVENTS]),
            actual_disconnect_ts=next(
                (e.ts for e in evts if e.event == "disconnect_detected"), None
            ),
        ))
    return results


def run_cell(framework: str, scenario: str, N: int, cancel_after: float,
             runs: int, settle: float, output: Path,
             T: int = 1, yield_interval_ms: int | None = None,
             cores: int | None = None, cpu_duration_s: int | None = None,
             per_run_output: Optional[Path] = None) -> None:
    """Run `runs` independent requests for one (framework, scenario, N) cell, append summary row."""
    cfg = FRAMEWORKS[framework]
    url = f"{cfg['url']}/{scenario}"
    container = cfg["container"]
    pw = POST_WAIT.get(framework, 2)
    all_metrics: list[RequestMetrics] = []

    print(f"  {framework} | {scenario} | N={N} | T={T} | K={yield_interval_ms}ms")
    for run in range(1, runs + 1):
        since = time.time()
        time.sleep(0.05)
        fire_concurrent(url, N, cancel_after)
        time.sleep(pw)
        events = collect_logs(container, since)
        metrics = parse_metrics(events, framework, run, scenario, int(cancel_after * 1000))
        all_metrics.extend(metrics)
        n_cancel = sum(1 for m in metrics if m.cancelled)
        l1_vals = [m.detection_latency_ms for m in metrics if m.detection_latency_ms is not None]
        l1_str = f"{statistics.mean(l1_vals):.0f}ms" if l1_vals else "n/a"
        print(f"    run {run}/{runs}: {len(metrics)} req  {n_cancel} cancelled  L1={l1_str}")
        if per_run_output is not None:
            n_req = len(metrics)
            l1 = _stat(l1_vals)
            write_per_run_csv(per_run_output, {
                "framework": framework, "scenario": scenario, "N": N, "T": T,
                "yield_interval_ms": yield_interval_ms, "run_index": run,
                "n_requests": n_req, "n_cancelled": n_cancel,
                "run_cancel_rate": round(n_cancel / n_req, 4) if n_req > 0 else "",
                "L1_mean": l1["mean"], "L1_sd": l1["sd"], "L1_median": l1["median"],
                "L1_min": l1["min"], "L1_max": l1["max"],
            })
        if run < runs:
            time.sleep(settle)

    row = compute_summary_row(all_metrics, framework, scenario, N, T,
                              int(cancel_after * 1000), yield_interval_ms, cores, cpu_duration_s)
    write_summary_csv(output, [row])
    rate = row["cancel_rate"]
    print(f"  → rate={rate}  written to {output.name}")
