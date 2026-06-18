#!/usr/bin/env python3
"""Analyses E3 resource-occupancy data (cross-check and cascade dynamics)."""

import argparse
import csv
import math
import statistics
from pathlib import Path
from typing import Optional

REPO = Path(__file__).parent.parent.parent
DATA = REPO / "experiments" / "sq3"


def _load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open() as f:
        return list(csv.DictReader(f))


def _float(v) -> Optional[float]:
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _int(v) -> Optional[int]:
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"



def analyse_e3a(data_dir: Path) -> None:
    rows = _load_csv(data_dir / "e3a" / "e3a_crosscheck.csv")
    if not rows:
        print("E3a: no data (e3a_crosscheck.csv not found)")
        return

    print("\n" + "═" * 72)
    print("E3a — Cross-check: ghost_holdtime vs wave2_delay")
    print("═" * 72)
    print(f"  {'Framework':<12} {'trials':>6}  "
          f"{'ghost_ms mean±sd':>18}  {'wave2_delay mean':>16}  "
          f"{'wave2_success':>13}  {'pool_wait%':>10}")
    print("  " + "─" * 72)

    by_fw: dict[str, list] = {}
    for r in rows:
        by_fw.setdefault(r["framework"], []).append(r)

    for fw, cell in sorted(by_fw.items()):
        n = len(cell)

        ghosts = [_float(r.get("wave1_ghost_holdtime_ms")) for r in cell]
        ghosts = [v for v in ghosts if v is not None]
        ghost_str = (f"{statistics.mean(ghosts):.0f}±{statistics.stdev(ghosts):.0f}"
                     if len(ghosts) >= 2 else (f"{ghosts[0]:.0f}" if ghosts else "n/a"))

        delays = [_float(r.get("wave2_delay_ms")) for r in cell]
        delays = [v for v in delays if v is not None]
        delay_str = (f"{statistics.mean(delays):.0f}ms"
                     if delays else "n/a")

        successes = [_float(r.get("wave2_success_rate")) for r in cell]
        successes = [v for v in successes if v is not None]
        success_str = (f"{statistics.mean(successes) * 100:.1f}%"
                       if successes else "n/a")

        n_pool_wait = sum(1 for r in cell if _int(r.get("pool_wait_visible")) == 1)
        pool_str = f"{_pct(n_pool_wait / n)}" if n > 0 else "n/a"

        print(f"  {fw:<12} {n:>6}  {ghost_str:>18}  {delay_str:>16}  {success_str:>13}  {pool_str:>10}")

        if ghosts and delays:
            delta_mean = statistics.mean(delays) - statistics.mean(ghosts)
            print(f"    wave2_delay − ghost_holdtime = {delta_mean:+.0f}ms "
                  f"({'✓ wave2 fired after ghost cleared' if delta_mean >= -100 else '⚠ wave2 fired before ghost cleared'})")

    print()
    print("Note: E3a is a setup validation, not a finding.")
    print("  wave2_delay ≈ ghost_holdtime confirms timing assumptions for E3c.")
    print("  pool_wait_visible = True → monitoring tooling would see latency spike in wave2.")



def analyse_e3c(data_dir: Path) -> None:
    rows = _load_csv(data_dir / "e3c" / "e3c_sustained.csv")
    if not rows:
        print("E3c: no data (e3c_sustained.csv not found)")
        return

    print("\n" + "═" * 84)
    print("E3c — Sustained Load: success/failure under pool pressure (symmetric metric)")
    print("═" * 84)
    print("  succeeded = HTTP 200; failed = any non-200 (503=R2DBC reject, 500=Npgsql pool")
    print("  timeout, to=client timeout); throughput counts ONLY successful (200) responses.")

    by_fw_XY: dict[tuple, list] = {}
    for r in rows:
        key = (r["framework"], _float(r.get("X_rps")), _float(r.get("Y_pct")))
        by_fw_XY.setdefault(key, []).append(r)

    mean_tput: dict[tuple, float] = {}
    mean_fail: dict[tuple, float] = {}

    for (fw, X, Y_pct), windows in sorted(by_fw_XY.items()):
        windows_sorted = sorted(windows, key=lambda r: _int(r.get("window_index")) or 0)
        n_win = len(windows_sorted)

        print(f"\n  {fw.upper()} | X={X}rps | Y={Y_pct}% cancel | {n_win} windows of 30s")
        print(f"  {'Win':>3} {'[s]':>8}  {'sent':>5}  {'ok':>5}  {'fail':>5}  {'fail%':>7}  "
              f"{'503':>4}  {'500':>4}  {'to':>4}  {'thru_ok':>8}  {'p95ms':>7}")
        print("  " + "─" * 76)

        for r in windows_sorted:
            wi = _int(r.get("window_index"))
            ws = int(_float(r.get("window_start_s")) or 0)
            we = int(_float(r.get("window_end_s")) or 0)
            sent = _int(r.get("requests_sent")) or 0
            ok = _int(r.get("succeeded")) or 0
            fail = _int(r.get("failed")) or 0
            ff = _float(r.get("failed_fraction")) or 0.0
            f503 = _int(r.get("failed_503")) or 0
            f500 = _int(r.get("failed_500")) or 0
            fto = _int(r.get("failed_timeout")) or 0
            tput = _float(r.get("throughput_rps_succeeded")) or 0.0
            p95 = _float(r.get("p95_latency_ms")) or 0.0
            print(f"  {wi:>3} [{ws:>3}–{we:>3}s]  {sent:>5}  {ok:>5}  {fail:>5}  {_pct(ff):>7}  "
                  f"{f503:>4}  {f500:>4}  {fto:>4}  {tput:>6.1f}rps  {p95:.0f}ms")

        fail_fracs = [_float(r.get("failed_fraction")) or 0.0 for r in windows_sorted]
        tputs = [_float(r.get("throughput_rps_succeeded")) or 0.0 for r in windows_sorted]
        tot_503 = sum(_int(r.get("failed_503")) or 0 for r in windows_sorted)
        tot_500 = sum(_int(r.get("failed_500")) or 0 for r in windows_sorted)
        tot_to = sum(_int(r.get("failed_timeout")) or 0 for r in windows_sorted)
        mode = max([("503", tot_503), ("500", tot_500), ("timeout", tot_to)], key=lambda kv: kv[1])

        mean_tput[(fw, X, Y_pct)] = statistics.mean(tputs)
        mean_fail[(fw, X, Y_pct)] = statistics.mean(fail_fracs)

        print()
        print(f"  Mean failure rate: {_pct(statistics.mean(fail_fracs))}  |  "
              f"mean successful throughput: {statistics.mean(tputs):.1f} rps")
        print(f"  Dominant failure mode: HTTP {mode[0]} "
              f"(503={tot_503}, 500={tot_500}, timeout={tot_to})")

    print()
    print("═" * 84)
    print("Ghost-connection contribution — successful throughput, Y=0% vs Y=10% (same X)")
    print("─" * 84)
    print(f"  {'FW':<10} {'X':>6}  {'thru Y=0%':>10}  {'thru Y=10%':>11}  {'ghost Δ':>9}")
    print("  " + "─" * 50)
    fws = sorted({fw for (fw, _, _) in by_fw_XY})
    Xs = sorted({X for (_, X, _) in by_fw_XY})
    for fw in fws:
        for X in Xs:
            t0 = mean_tput.get((fw, X, 0.0))
            t10 = mean_tput.get((fw, X, 10.0))
            if t0 is None or t10 is None:
                continue
            delta = (t10 - t0) / t0 * 100 if t0 > 0 else float("nan")
            print(f"  {fw:<10} {X:>6}  {t0:>8.1f}rps  {t10:>9.1f}rps  {delta:>+7.1f}%")

    print()
    print("═" * 84)
    print("Failure-mode asymmetry (why a 503-only metric mislabels ASP.NET)")
    print("─" * 84)
    for fw in fws:
        s503 = sum(_int(r.get("failed_503")) or 0 for (f, _, _), ws in by_fw_XY.items() if f == fw for r in ws)
        s500 = sum(_int(r.get("failed_500")) or 0 for (f, _, _), ws in by_fw_XY.items() if f == fw for r in ws)
        sto = sum(_int(r.get("failed_timeout")) or 0 for (f, _, _), ws in by_fw_XY.items() if f == fw for r in ws)
        print(f"  {fw:<10} 503={s503:>6}  500={s500:>6}  timeout={sto:>6}")
    print()
    print("Honest reading: at pool=10 with 10s queries, baseline load saturates the pool for")
    print("  BOTH frameworks (~1 successful req/s); the ghost-Δ (Y=0 vs Y=10) is the clean,")
    print("  architecture-attributable effect. The frameworks fail with DIFFERENT status codes")
    print("  (WebFlux 503, ASP.NET 500-after-timeout) — a 503-only metric sees only WebFlux.")



def main() -> None:
    parser = argparse.ArgumentParser(description="E3 analysis — resource occupancy (SQ3)")
    parser.add_argument("--only", choices=["e3a", "e3c", "all"], default="all")
    args = parser.parse_args()

    if args.only in ("e3a", "all"):
        analyse_e3a(DATA)
    if args.only in ("e3c", "all"):
        analyse_e3c(DATA)


if __name__ == "__main__":
    main()
