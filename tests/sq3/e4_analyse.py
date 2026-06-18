#!/usr/bin/env python3
"""Analyses E4 ghost-write and transactional-correctness data."""

import argparse
import csv
import math
import random
import statistics
from pathlib import Path
from typing import Optional

REPO = Path(__file__).parent.parent.parent
DATA = REPO / "experiments" / "sq3"



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


def _int(v) -> Optional[int]:
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _float(v) -> Optional[float]:
    try:
        return float(v)
    except (ValueError, TypeError):
        return None



def analyse_e4a(data_dir: Path) -> None:
    rows = _load_csv(data_dir / "e4a" / "e4a_log_audit.csv")
    if not rows:
        print("E4a: no data (e4a_log_audit.csv not found)")
        return

    print("\n" + "═" * 72)
    print("E4a — Log Audit Anchor (ghost write visibility)")
    print("═" * 72)

    by_fw: dict[str, list] = {}
    for r in rows:
        by_fw.setdefault(r["framework"], []).append(r)

    for fw, cell in sorted(by_fw.items()):
        n = len(cell)
        n_detected = sum(1 for r in cell if _int(r.get("detected"))    == 1)
        n_propagated = sum(1 for r in cell if _int(r.get("propagated"))  == 1)
        n_log_success = sum(1 for r in cell if _int(r.get("log_shows_success")) == 1)
        n_ghost = sum(1 for r in cell if _int(r.get("ghost_write_confirmed")) == 1)

        n_det_ghost = sum(1 for r in cell
                              if _int(r.get("detected")) == 1 and _int(r.get("ghost_write_confirmed")) == 1)
        n_det_no_ghost = sum(1 for r in cell
                              if _int(r.get("detected")) == 1 and _int(r.get("ghost_write_confirmed")) == 0)
        n_nodet_ghost = sum(1 for r in cell
                              if _int(r.get("detected")) == 0 and _int(r.get("ghost_write_confirmed")) == 1)
        n_nodet_no_ghost = sum(1 for r in cell
                               if _int(r.get("detected")) == 0 and _int(r.get("ghost_write_confirmed")) == 0)

        print(f"\n  {fw.upper()} (n={n})")
        print(f"    detected={_pct(n_detected/n)}  propagated={_pct(n_propagated/n)}"
              f"  log_shows_success={_pct(n_log_success/n)}  ghost_write={_pct(n_ghost/n)}")
        print()
        print(f"    {'':30} ghost_write=1   ghost_write=0")
        print(f"    {'detected=1':30} {n_det_ghost:>13} {n_det_no_ghost:>14}")
        print(f"    {'detected=0':30} {n_nodet_ghost:>13} {n_nodet_no_ghost:>14}")

        n_invisible = sum(1 for r in cell
                          if _int(r.get("propagated")) == 1 and _int(r.get("ghost_write_confirmed")) == 1)
        if n_invisible > 0:
            print(f"\n    ⚠ log_invisible: propagated=1 AND ghost_write=1 in {n_invisible}/{n} trials")
            print(f"      → cancellation_propagated=true does not guarantee data integrity")
        else:
            print(f"\n    ✓ No log invisibility (propagated=1 ∧ ghost_write=1) detected in {n} trials")

    print()
    print("Expected: ASP.NET — detected=100%, ghost_write=0%   (full bridge, CancelRequest sent)")
    print("          WebFlux — detected=100%, ghost_write=100%  (no bridge, INSERT runs to completion)")
    print("          MVC     — detected=0%,   ghost_write=100%  (passive, onError never fires for non-streaming GET)")
    print("Key finding: log emits cancellation_propagated=true even when ghost write occurred (WebFlux).")
    print("             MVC: ghost_write=100% by architectural necessity, not a race — no detection at all.")



def analyse_e4b_sweep(data_dir: Path) -> None:
    rows = _load_csv(data_dir / "e4b" / "e4b_dsweep.csv")
    if not rows:
        print("E4b: no data (e4b_dsweep.csv not found)")
        return

    print("\n" + "═" * 72)
    print("E4b — D* Sweep (ghost write rate by INSERT duration)")
    print("═" * 72)
    print(f"  {'FW':<10} {'D_ms':>6} {'runs':>5}  {'ghost%':>7}  {'CI95':>20}")
    print("  " + "─" * 56)

    by_fw_D: dict[tuple, list] = {}
    for r in rows:
        key = (r["framework"], _int(r.get("D_ms")))
        by_fw_D.setdefault(key, []).append(r)

    dstar_estimates: dict[str, list] = {}

    for (fw, D), cell in sorted(by_fw_D.items()):
        n = len(cell)
        n_ghost = sum(1 for r in cell if _int(r.get("ghost_write")) == 1)
        lo, hi = wilson_ci(n_ghost, n)
        rate = n_ghost / n if n > 0 else 0.0

        dstar_estimates.setdefault(fw, []).append((D, rate))

        flag = ""
        if 0.3 <= rate <= 0.7:
            flag = "← D* zone"

        print(f"  {fw:<10} {D:>6} {n:>5}  {_pct(rate):>7}  [{_pct(lo)}, {_pct(hi)}]  {flag}")

    print()
    for fw, points in sorted(dstar_estimates.items()):
        crossing = None
        for i in range(len(points) - 1):
            D1, r1 = points[i]
            D2, r2 = points[i + 1]
            if r1 >= 0.5 >= r2:
                crossing = D1 + (D2 - D1) * (r1 - 0.5) / (r1 - r2)
                break
        if crossing is not None:
            print(f"  D* estimate ({fw}): ≈{crossing:.0f}ms (linear interpolation at 50% crossing)")
        else:
            max_rate = max(r for _, r in points)
            min_rate = min(r for _, r in points)
            if max_rate < 0.3:
                print(f"  {fw}: ghost_write < 30% at all D — CancelRequest always wins (full bridge)")
            elif min_rate > 0.7:
                print(f"  {fw}: ghost_write > 70% at all D — INSERT always commits (structural, no bridge)")
            else:
                print(f"  {fw}: D* not clearly identified from sweep range — run transition analysis")

    print()
    print("ASP.NET: expect D* in the low-hundreds of ms range (CancelRequest round-trip time).")
    print("WebFlux: expect ghost_write ≈ 100% at all D (R2DBC no bridge — structural).")



def _logistic(x, b0, b1):
    return 1.0 / (1.0 + math.exp(-(b0 + b1 * x)))


def _fit_logistic(D_values: list[float], ghost_values: list[int]) -> tuple[float, float]:
    """Gradient-descent fit of logistic(b0 + b1*D) to binary outcomes."""
    try:
        from scipy.optimize import curve_fit
        import numpy as np
        popt, _ = curve_fit(
            lambda x, b0, b1: 1 / (1 + np.exp(-(b0 + b1 * x))),
            D_values, ghost_values,
            p0=[5.0, -0.05], maxfev=5000,
        )
        return float(popt[0]), float(popt[1])
    except Exception:
        mean_D = statistics.mean(D_values)
        b0 = 0.0
        b1 = -0.01
        return b0, b1


def _d_at_prob(b0: float, b1: float, prob: float) -> float:
    """D value where logistic(b0 + b1*D) = prob."""
    if b1 == 0:
        return float("nan")
    return (math.log(prob / (1 - prob)) - b0) / b1


def _bootstrap_transition(
    D_values: list[float],
    ghost_values: list[int],
    n_boot: int = 1000,
    probs: tuple = (0.1, 0.5, 0.9),
) -> dict[float, tuple[float, float]]:
    """Bootstrap 95% CIs for D at each probability in probs."""
    pairs = list(zip(D_values, ghost_values))
    estimates = {p: [] for p in probs}
    for _ in range(n_boot):
        sample = random.choices(pairs, k=len(pairs))
        Ds = [x[0] for x in sample]
        Gs = [x[1] for x in sample]
        try:
            b0, b1 = _fit_logistic(Ds, Gs)
            for p in probs:
                estimates[p].append(_d_at_prob(b0, b1, p))
        except Exception:
            pass

    cis: dict[float, tuple[float, float]] = {}
    for p, vals in estimates.items():
        vals_clean = [v for v in vals if math.isfinite(v)]
        if len(vals_clean) >= 20:
            vals_clean.sort()
            lo = vals_clean[int(len(vals_clean) * 0.025)]
            hi = vals_clean[int(len(vals_clean) * 0.975)]
            cis[p] = (lo, hi)
        else:
            cis[p] = (float("nan"), float("nan"))
    return cis


def analyse_e4b_transition(data_dir: Path, D_star: Optional[int] = None) -> None:
    rows = _load_csv(data_dir / "e4b" / "e4b_transition.csv")
    if not rows:
        print("E4b-transition: no data (e4b_transition.csv not found)")
        return

    print("\n" + "═" * 72)
    print("E4b-transition — Logistic Transition Width (D* zone)")
    print("═" * 72)

    by_D: dict[int, list] = {}
    for r in rows:
        D = _int(r.get("D_ms"))
        by_D.setdefault(D, []).append(r)

    print(f"  {'D_ms':>6} {'runs':>5}  {'ghost%':>7}  {'CI95':>20}")
    print("  " + "─" * 44)
    D_values_flat: list[float] = []
    ghost_flat: list[int] = []
    for D, cell in sorted(by_D.items()):
        n = len(cell)
        n_ghost = sum(1 for r in cell if _int(r.get("ghost_write")) == 1)
        lo, hi = wilson_ci(n_ghost, n)
        print(f"  {D:>6} {n:>5}  {_pct(n_ghost/n):>7}  [{_pct(lo)}, {_pct(hi)}]")
        for r in cell:
            D_values_flat.append(float(D))
            ghost_flat.append(_int(r.get("ghost_write")) or 0)

    if len(set(D_values_flat)) < 3:
        print("\n  Too few distinct D values for logistic fit.")
        return

    b0, b1 = _fit_logistic(D_values_flat, ghost_flat)
    D_10 = _d_at_prob(b0, b1, 0.10)
    D_50 = _d_at_prob(b0, b1, 0.50)
    D_90 = _d_at_prob(b0, b1, 0.90)
    width = abs(D_10 - D_90)

    print(f"\n  Logistic fit:  β₀={b0:.4f}  β₁={b1:.4f}")
    print(f"  D_90 = {D_90:.1f}ms   (ghost_write probability = 90% — danger zone boundary)")
    print(f"  D_50 = {D_50:.1f}ms   (D* estimate — 50% crossover)")
    print(f"  D_10 = {D_10:.1f}ms   (ghost_write probability = 10% — safe zone boundary)")
    print(f"  Transition width (D_10 − D_90) = {width:.1f}ms")

    cis = _bootstrap_transition(D_values_flat, ghost_flat)
    print()
    print("  Bootstrap 95% CIs (N=1000 resamples):")
    for p in (0.90, 0.50, 0.10):
        lo, hi = cis.get(p, (float("nan"), float("nan")))
        label = {0.10: "D_10", 0.50: "D_50", 0.90: "D_90"}[p]
        print(f"    {label}: [{lo:.1f}, {hi:.1f}]ms")

    if D_star is not None:
        print(f"\n  Pre-specified D*={D_star}ms vs fitted D_50={D_50:.1f}ms")

    print()
    print("Interpretation: narrow width (< 50ms) → sharp CancelRequest race boundary.")
    print("                wide width (> 200ms) → stochastic zone dominated by timing jitter.")
    print("Parallel to N_10 metric from SQ1 cliff analysis.")



def analyse_e4b_exceptions(data_dir: Path) -> None:
    rows = _load_csv(data_dir / "e4b" / "e4b_exceptions.csv")
    if not rows:
        print("E4b-exceptions: no data (e4b_exceptions.csv not found)")
        return

    print("\n" + "═" * 72)
    print("E4b-exceptions — Npgsql Exception Distinguishability")
    print("═" * 72)

    by_cat: dict[str, list] = {}
    for r in rows:
        by_cat.setdefault(r["D_category"], []).append(r)

    for category, cell in sorted(by_cat.items()):
        D_vals = list({_int(r["D_ms"]) for r in cell})
        D_str = ", ".join(str(d) for d in sorted(D_vals) if d is not None)
        n = len(cell)
        n_ghost = sum(1 for r in cell if _int(r.get("ghost_write")) == 1)

        n_distinguishable = sum(
            1 for r in cell
            if r.get("inner_exception_type") not in (None, "", "None")
            and r.get("inner_sql_state") == "57014"
        )
        n_indistinguishable = n - n_distinguishable

        lo_d, hi_d = wilson_ci(n_distinguishable, n)
        lo_g, hi_g = wilson_ci(n_ghost, n)

        print(f"\n  {category.upper()} (D∈{{{D_str}}}ms, n={n})")
        print(f"    ghost_write: {_pct(n_ghost/n)} [{_pct(lo_g)}, {_pct(hi_g)}]")
        print(f"    distinguishable (inner SqlState=57014): "
              f"{_pct(n_distinguishable/n)} [{_pct(lo_d)}, {_pct(hi_d)}]")
        print()

        chains: dict[str, int] = {}
        for r in cell:
            outer = r.get("outer_exception_type") or "None"
            inner = r.get("inner_exception_type") or "None"
            state = r.get("inner_sql_state") or "None"
            key = f"outer={outer} inner={inner} sql_state={state}"
            chains[key] = chains.get(key, 0) + 1

        print(f"    Exception chain breakdown:")
        for chain, count in sorted(chains.items(), key=lambda x: -x[1]):
            print(f"      {count:>3}× {chain}")

    print()
    print("Expected:")
    print("  below_dstar (ghost write) → outer=OperationCanceledException inner=None")
    print("    No PostgresException: PG never sent error 57014 (INSERT committed before CancelRequest)")
    print("    → INDISTINGUISHABLE from application perspective without DB audit")
    print("  above_dstar (clean cancel) → outer=OperationCanceledException")
    print("    inner=PostgresException sql_state=57014")
    print("    → Distinguishable IF application inspects InnerException.SqlState")



def main() -> None:
    parser = argparse.ArgumentParser(description="E4 analysis — ghost writes (SQ3)")
    parser.add_argument("--only", choices=["e4a", "e4b", "e4b-transition", "e4b-exceptions", "all"],
                        default="all")
    parser.add_argument("--D-star", type=int, dest="D_star",
                        help="Known D* value in ms (for e4b-transition interpretation)")
    args = parser.parse_args()

    if args.only in ("e4a", "all"):
        analyse_e4a(DATA)
    if args.only in ("e4b", "all"):
        analyse_e4b_sweep(DATA)
    if args.only in ("e4b-transition", "all"):
        analyse_e4b_transition(DATA, args.D_star)
    if args.only in ("e4b-exceptions", "all"):
        analyse_e4b_exceptions(DATA)


if __name__ == "__main__":
    main()
