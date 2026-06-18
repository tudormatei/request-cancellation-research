#!/usr/bin/env python3
"""Probes connection-pool occupancy under sustained cancellation load, both frameworks."""
import argparse
import csv
import subprocess
import threading
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import FRAMEWORKS, fire_sustained

REPO = Path(__file__).parent.parent.parent
OUT = REPO / "experiments" / "sq3" / "e3c" / "e3_capacity_probe.csv"
PG = "thesis_postgres"


def q(sql: str) -> int:
    try:
        r = subprocess.run(
            ["docker", "exec", PG, "psql", "-U", "thesisuser", "-d", "thesisdb", "-tAc", sql],
            capture_output=True, text=True, timeout=5)
        return int((r.stdout or "0").strip() or 0)
    except Exception:
        return -1


def counts():
    active = q("SELECT count(*) FROM pg_stat_activity WHERE state='active' AND query LIKE 'SELECT pg_sleep%'")
    total = q("SELECT count(*) FROM pg_stat_activity WHERE datname='thesisdb' "
               "AND backend_type='client backend' AND query NOT LIKE '%pg_stat_activity%'")
    idletx = q("SELECT count(*) FROM pg_stat_activity WHERE datname='thesisdb' AND state='idle in transaction'")
    return active, total, idletx


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--framework", required=True, choices=["aspnet", "webflux"])
    p.add_argument("--pool", type=int, required=True)
    p.add_argument("--X", type=float, required=True)
    p.add_argument("--Y", type=float, default=0.8)
    p.add_argument("--cancel-after", type=float, default=0.5)
    p.add_argument("--duration", type=int, default=120)
    a = p.parse_args()

    url = f"{FRAMEWORKS[a.framework]['url']}/db"
    series = []
    stop = threading.Event()
    t0 = time.time()

    def poll():
        while not stop.is_set():
            ac, to, it = counts()
            series.append((round(time.time() - t0, 1), ac, to, it))
            time.sleep(0.5)

    pt = threading.Thread(target=poll, daemon=True)
    pt.start()
    print(f"\nprobe {a.framework} | pool={a.pool} X={a.X} Y={a.Y} cancel@{a.cancel_after} | duration={a.duration}s")
    fire_sustained(url=url, rate_rps=a.X, cancel_fraction=a.Y, cancel_after_s=a.cancel_after,
                   duration_s=a.duration, window_s=30.0)
    time.sleep(8)
    stop.set()
    pt.join(timeout=2)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    new = not OUT.exists()
    with OUT.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["framework", "pool", "X", "t_s", "active_pgsleep", "total_conns", "idle_in_tx"])
        for t, ac, to, it in series:
            w.writerow([a.framework, a.pool, a.X, t, ac, to, it])

    load_end = a.duration
    half = [to for t, ac, to, it in series if load_end / 2 <= t <= load_end and to >= 0]
    half.sort()
    med = half[len(half) // 2] if half else -1
    peak = max((to for _, _, to, _ in series if to >= 0), default=-1)
    print(f"  steady-state (2nd half) median total_conns = {med} ; peak = {peak} ; pool = {a.pool}")


if __name__ == "__main__":
    main()
