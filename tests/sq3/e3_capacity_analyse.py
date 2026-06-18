#!/usr/bin/env python3
"""Extracts X_max per framework/pool from the E3 capacity occupancy probe."""
import csv
import statistics
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).parent.parent.parent
CSV = REPO / "experiments" / "sq3" / "e3c" / "e3_capacity_probe.csv"
OUT = REPO / "experiments" / "sq3" / "e3c" / "e3_capacity_xmax.csv"


def steady_active(rows):
    ts = [float(r["t_s"]) for r in rows]
    tmax = max(ts)
    occ = [int(r["active_pgsleep"]) for r in rows
           if 0.5 * tmax <= float(r["t_s"]) <= 0.95 * tmax and int(r["active_pgsleep"]) >= 0]
    return statistics.median(occ) if occ else -1.0


def fit_slope_xmax(pts, pool):
    """pts: [(X, active_occ)]. Slope (E[S]) through origin on unsaturated points; X_max=pool/slope."""
    un = [(x, o) for x, o in pts if 0 < o < 0.85 * pool]
    use = un if len(un) >= 2 else [(x, o) for x, o in pts if o < pool]
    num = sum(x * o for x, o in use)
    den = sum(x * x for x, o in use)
    m = num / den if den else float("nan")
    return m, (pool / m if m else float("nan")), len(use)


def main():
    rows = list(csv.DictReader(CSV.open()))
    cells = defaultdict(list)
    for r in rows:
        cells[(r["framework"], int(r["pool"]), float(r["X"]))].append(r)

    occ_by_fp = defaultdict(list)
    for (fw, pool, X), rs in cells.items():
        occ_by_fp[(fw, pool)].append((X, steady_active(rs)))

    out = []
    print(f"{'framework':8} {'pool':>4} {'(X, active_occ)':<40} {'E[S]':>6} {'X_max':>7} {'n':>3}")
    for (fw, pool) in sorted(occ_by_fp):
        pts = sorted(occ_by_fp[(fw, pool)])
        m, xmax, n = fit_slope_xmax(pts, pool)
        pretty = " ".join(f"({x:g},{o:g})" for x, o in pts)
        print(f"{fw:8} {pool:>4} {pretty:<40} {m:>6.2f} {xmax:>7.2f} {n:>3}")
        out.append((fw, pool, round(m, 3), round(xmax, 3), n))

    with OUT.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["framework", "pool", "slope_Es", "X_max", "n_used"])
        w.writerows(out)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
