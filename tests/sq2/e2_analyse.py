#!/usr/bin/env python3
"""Analyses E2 IO cancellation protocol results (outbound HTTP, single-result DB, streaming DB)."""

import argparse
import csv
import math
import statistics
from pathlib import Path
from typing import Optional

REPO = Path(__file__).parent.parent.parent
DATA = REPO / "experiments" / "sq2"



def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open() as f:
        return list(csv.DictReader(f))


def _float(v: str) -> Optional[float]:
    try:
        return float(v)
    except (ValueError, TypeError):
        return None



def analyse_e2c(data_dir: Path) -> None:
    rows = _load_csv(data_dir / "e2c" / "e2c_outbound.csv")
    if not rows:
        print("E2c: no data (e2c_outbound.csv not found)")
        return

    print("\n" + "═" * 70)
    print("E2c — Outbound HTTP Cancellation (Connection-Close Protocol)")
    print("═" * 70)
    print(f"{'Framework':<12} {'N':>4} {'Runs':>5}  "
          f"{'Outbound%':>10}  {'CI95':>18}  "
          f"{'DS conf%':>9}  {'Lat mean±sd ms':>16}")
    print("─" * 70)

    by_fw_N: dict[tuple, list] = {}
    for r in rows:
        key = (r["framework"], int(r["N"]))
        by_fw_N.setdefault(key, []).append(r)

    for (fw, N), cell in sorted(by_fw_N.items()):
        n = len(cell)
        n_outbound = sum(1 for r in cell if _float(r.get("outbound_cancelled", "0")) == 1.0)
        n_ds = sum(1 for r in cell if r.get("downstream_confirmed") == "1")
        lo, hi = wilson_ci(n_outbound, n)

        lats = [_float(r.get("outbound_cancel_latency_ms")) for r in cell]
        lats = [v for v in lats if v is not None]
        lat_str = (f"{statistics.mean(lats):.0f}±{statistics.stdev(lats):.0f}"
                   if len(lats) >= 2 else "n/a")

        print(f"  {fw:<12} {N:>4} {n:>5}  "
              f"{_pct(n_outbound/n):>10}  [{_pct(lo)}, {_pct(hi)}]  "
              f"{_pct(n_ds/n):>9}  {lat_str:>16}")

    print()
    print("Expected: 100% outbound_cancelled and downstream_confirmed for both frameworks.")
    print("Interpretation: connection-close protocol — no bridge required, cancellation is automatic.")



def analyse_e2a(data_dir: Path) -> None:
    rows = _load_csv(data_dir / "e2a" / "e2a_db.csv")
    if not rows:
        print("E2a: no data (e2a_db.csv not found)")
        return

    print("\n" + "═" * 80)
    print("E2a — Single-Result DB Query (Full Bridge vs No Bridge)")
    print("═" * 80)
    print(f"{'FW':<10} {'N':>4} {'runs':>5}  "
          f"{'det%':>6}  {'db_cancel%':>11}  {'CI95':>18}  "
          f"{'ratio':>7}  {'ghost_ms':>10}  {'cancel_lat_ms':>14}")
    print("─" * 80)

    by_fw_N: dict[tuple, list] = {}
    for r in rows:
        key = (r["framework"], int(r["N"]))
        by_fw_N.setdefault(key, []).append(r)

    for (fw, N), cell in sorted(by_fw_N.items()):
        n = len(cell)

        det_rates = [_float(r.get("detection_rate")) for r in cell]
        det_rates = [v for v in det_rates if v is not None]
        det_mean = statistics.mean(det_rates) if det_rates else 0

        n_db_cancel = sum(1 for r in cell if r.get("db_cancelled") == "1")
        lo, hi = wilson_ci(n_db_cancel, n)
        db_rate = n_db_cancel / n if n else 0

        ratio_str = (f"{db_rate / det_mean:.2f}" if det_mean > 0 else "n/a")

        ghosts = [_float(r.get("ghost_holdtime_ms")) for r in cell]
        ghosts = [v for v in ghosts if v is not None]
        ghost_str = (f"{statistics.mean(ghosts):.0f}±{statistics.stdev(ghosts):.0f}"
                      if len(ghosts) >= 2 else "n/a")

        lats = [_float(r.get("db_cancel_latency_ms")) for r in cell]
        lats = [v for v in lats if v is not None]
        lat_str = (f"{statistics.mean(lats):.0f}±{statistics.stdev(lats):.0f}"
                   if len(lats) >= 2 else "n/a")

        print(f"  {fw:<10} {N:>4} {n:>5}  "
              f"{_pct(det_mean):>6}  {_pct(db_rate):>11}  [{_pct(lo)}, {_pct(hi)}]  "
              f"{ratio_str:>7}  {ghost_str:>10}  {lat_str:>14}")

    print()
    print("Key metrics:")
    print("  db_cancel% (ASP.NET)  → should ≈ detection%, ratio ≈ 1.0 across all N")
    print("  db_cancel% (WebFlux)  → should = 0% at all N (R2DBC no bridge, issue #251)")
    print("  ghost_ms   (WebFlux)  → should ≈ 4000ms (remaining query time: 10s − 6s)")
    print("  ratio drop at high N  → secondary Npgsql CancelRequest throughput bottleneck")



def analyse_e2b(data_dir: Path) -> None:
    rows = _load_csv(data_dir / "e2b" / "e2b_stream.csv")
    if not rows:
        print("E2b: no data (e2b_stream.csv not found)")
        return

    print("\n" + "═" * 70)
    print("E2b — Streaming DB Query (Consumption Bridge)")
    print("═" * 70)
    print(f"{'Framework':<12} {'N':>4} {'runs':>5}  "
          f"{'cursor%':>8}  {'CI95':>18}  "
          f"{'rows_mean':>10}  {'ghost_ms':>10}")
    print("─" * 70)

    by_fw_N: dict[tuple, list] = {}
    for r in rows:
        key = (r["framework"], int(r["N"]))
        by_fw_N.setdefault(key, []).append(r)

    for (fw, N), cell in sorted(by_fw_N.items()):
        n = len(cell)
        n_cursor = sum(1 for r in cell if _float(r.get("cursor_cancelled", "0")) == 1.0)
        lo, hi = wilson_ci(n_cursor, n)

        rows_vals = [_float(r.get("rows_consumed")) for r in cell]
        rows_vals = [v for v in rows_vals if v is not None]
        rows_str = f"{statistics.mean(rows_vals):.0f}" if rows_vals else "n/a"

        ghosts = [_float(r.get("ghost_holdtime_ms")) for r in cell]
        ghosts = [v for v in ghosts if v is not None]
        ghost_str = (f"{statistics.mean(ghosts):.0f}±{statistics.stdev(ghosts):.0f}"
                     if len(ghosts) >= 2 else "n/a")

        print(f"  {fw:<12} {N:>4} {n:>5}  "
              f"{_pct(n_cursor/n):>8}  [{_pct(lo)}, {_pct(hi)}]  "
              f"{rows_str:>10}  {ghost_str:>10}")

    print()
    print("ASP.NET: ghost_holdtime 84–119ms (CancelRequest fired — full bridge confirmed for streaming).")
    print("WebFlux: ghost_holdtime ~31s (N-independent) — remaining query duration.")
    print("  Consumption bridge = Reactor subscriber cancelled, PostgreSQL continues unconditionally.")
    print("  Under sequential load: connections abandoned by pool → indefinite ClientWrite (>420s).")
    print("Contrast: consumption bridge vs no bridge produce same server-side holdtime (= remaining query time).")



def print_synthesis() -> None:
    print("\n" + "═" * 78)
    print("SQ2 Synthesis — IO Cancellation Protocol × Driver Bridge State")
    print("═" * 78)
    print(f"{'IO type':<22} {'Protocol':<22} {'Framework':<14} {'Bridge':<20} {'Server cancel?'}")
    print("─" * 78)
    rows = [
        ("DB single-result", "Out-of-band abort", "ASP.NET (Npgsql)", "Full bridge",        "✓ (CancelRequest)"),
        ("DB single-result", "Out-of-band abort", "WebFlux (R2DBC)",  "No bridge",           "✗ (runs to completion)"),
        ("DB streaming",     "Out-of-band abort", "ASP.NET (Npgsql)", "Full bridge",         "✓ (CancelRequest)"),
        ("DB streaming",     "Out-of-band abort", "WebFlux (R2DBC)",  "Consumption bridge",  "Partial (cursor closed)"),
        ("Outbound HTTP",    "Connection-close",  "ASP.NET",          "Protocol-automatic",  "✓"),
        ("Outbound HTTP",    "Connection-close",  "WebFlux",          "Protocol-automatic",  "✓"),
    ]
    for io, proto, fw, bridge, result in rows:
        print(f"  {io:<22} {proto:<22} {fw:<14} {bridge:<20} {result}")
    print()
    print("Conclusion: propagation depth is determined by IO protocol + driver bridge state.")
    print("Framework architecture (cooperative vs reactive) determines detection, not bridge state.")
    print("E2c falsifies 'WebFlux cannot cancel IO' — it can, when the protocol allows it.")



def main() -> None:
    parser = argparse.ArgumentParser(description="E2 analysis")
    parser.add_argument("--only", choices=["e2a", "e2b", "e2c", "all"], default="all")
    args = parser.parse_args()

    if args.only in ("e2c", "all"):
        analyse_e2c(DATA)
    if args.only in ("e2a", "all"):
        analyse_e2a(DATA)
    if args.only in ("e2b", "all"):
        analyse_e2b(DATA)
    if args.only == "all":
        print_synthesis()


if __name__ == "__main__":
    main()
