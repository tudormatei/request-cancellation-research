#!/usr/bin/env python3
"""Analyses SQ1 enhancement experiments A1-A4 (scheduler, Go cliff, blind, no-injection)."""

import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sp

REPO = Path(__file__).parent.parent.parent
DATA = REPO / "experiments" / "sq1"
E1A = DATA / "e1a"


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    centre = (k + z**2 / 2) / (n + z**2)
    margin = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / (1 + z**2 / n)
    return max(0.0, centre - margin), min(1.0, centre + margin)


def _load_per_run(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        print(f"  missing: {path.name}")
        return None
    df = pd.read_csv(path)
    dropped = int((df["n_requests"] > df["N"]).sum())
    if dropped:
        print(f"  [W1-6] dropped {dropped} bleed-over run(s) with n_requests > N in {path.name}")
    return df[df["n_requests"] <= df["N"]].copy()


def _pn_table(df: pd.DataFrame, group_cols=("N",)) -> list[tuple]:
    """Return rows of (key..., n_fail, n_total, p_fail, lo, hi) grouped by group_cols."""
    df = df.copy()
    df["failed"] = (df["n_cancelled"] == 0).astype(int)
    rows = []
    for key, grp in df.groupby(list(group_cols)):
        n_total = len(grp)
        n_fail = int(grp["failed"].sum())
        lo, hi = wilson_ci(n_fail, n_total)
        key_t = key if isinstance(key, tuple) else (key,)
        rows.append((*key_t, n_fail, n_total, n_fail / n_total, lo, hi))
    return rows


def _n10(df_k: pd.DataFrame) -> int | None:
    """First N with p_fail >= 10% (W1-6 filtered df for a single K).
    _pn_table rows are (N, n_fail, n_total, p_fail, lo, hi) — p_fail is index 3."""
    rows = sorted(_pn_table(df_k, ("N",)))
    return next((int(r[0]) for r in rows if r[3] >= 0.10), None)



def analyse_a1() -> None:
    print("\n" + "═" * 64)
    print("A1 — within-WebFlux scheduler isolation (K=100ms, C=1)")
    print("═" * 64)
    for label, fname in [("boundedElastic (idiomatic)", "e1f_webflux_be_runs.csv"),
                         ("immediate (probe)",          "e1f_webflux_imm_runs.csv")]:
        df = _load_per_run(E1A / fname)
        if df is None:
            continue
        print(f"\n{label}:")
        print(f"  {'N':>6}  {'detect%':>8}  {'CI_lo':>6}  {'CI_hi':>6}  {'runs':>5}")
        for N, nf, nt, pf, lo, hi in sorted(_pn_table(df, ("N",))):
            det = 1 - pf
            print(f"  {int(N):>6}  {det:>8.1%}  {1-hi:>6.1%}  {1-lo:>6.1%}  {nt:>5}")
    print("\n  → Interpretation: if `immediate` collapses at all N (incl. N=1) while")
    print("    `boundedElastic` stays flat, load-invariance = detection-context isolation,")
    print("    not 'reactive' per se (Finding E1-12).")



def analyse_a2() -> None:
    print("\n" + "═" * 64)
    print("A2 — Go cooperative-token replication (C=1)")
    print("═" * 64)
    df = _load_per_run(E1A / "e1g_go_cliff_runs.csv")
    if df is not None:
        for K, grp in sorted(df.groupby("yield_interval_ms")):
            print(f"\nK={int(K)}ms:  (per-REQUEST mean cancel rate — Go is graded, not all-or-nothing)")
            print(f"  {'N':>6}  {'cancel%':>8}  {'sd':>6}  {'runs@1.0':>8}  {'runs@0.0':>8}  {'runs':>5}")
            nsafe = None
            for N, g in sorted(grp.groupby("N")):
                r = g["run_cancel_rate"]
                mean = float(r.mean())
                print(f"  {int(N):>6}  {mean:>8.1%}  {float(r.std()):>6.3f}"
                      f"  {int((r > 0.99).sum()):>8}  {int((r < 0.01).sum()):>8}  {len(g):>5}")
                if nsafe is None and mean < 0.90:
                    nsafe = int(N)
            if nsafe is None:
                print(f"  → no degradation: per-request cancel ≥90% across all tested N")
            else:
                print(f"  → N_safe (first N with mean per-request cancel <90%) = {nsafe}")
    lat = E1A / "e1g_go_latency_runs.csv"
    if lat.exists():
        ldf = pd.read_csv(lat)
        print("\nGo detection latency (N=1) vs K:")
        print(f"  {'K_ms':>6}  {'L1_median':>10}  {'L1/K':>6}")
        for K, grp in sorted(ldf.groupby("yield_interval_ms")):
            med = grp["L1_median"].median()
            print(f"  {int(K):>6}  {med:>10.1f}  {med/float(K):>6.2f}")



def analyse_a3() -> None:
    print("\n" + "═" * 64)
    print("A3 — blind prediction at C=2, K=300ms")
    print("═" * 64)
    df = _load_per_run(E1A / "e1a_blind_C2_K300_runs.csv")
    if df is None:
        return
    print(f"\n  {'N':>6}  {'p_fail':>7}  {'CI_lo':>6}  {'CI_hi':>6}  {'runs':>5}")
    for N, nf, nt, pf, lo, hi in sorted(_pn_table(df, ("N",))):
        print(f"  {int(N):>6}  {pf:>7.1%}  {lo:>6.1%}  {hi:>6.1%}  {nt:>5}")
    predicted = 5499 * 2 / (300 ** 0.880)
    n10 = _n10(df)
    print(f"\n  Predicted N_safe ≈ {predicted:.0f}  (5499·2 / 300^0.880)")
    print(f"  Observed N_10    = {n10}")
    if n10:
        err = abs(n10 - predicted) / predicted * 100
        print(f"  Error = {err:.0f}%  {'✓ within 20% (formula behaves as a law)' if err <= 20 else '✗ outside 20% (documented formula limit)'}")



def analyse_a4() -> None:
    print("\n" + "═" * 64)
    print("A4 — no thread-injection probe (C=1, MIN=MAX=N)")
    print("═" * 64)
    pts = []
    for K in (100, 200, 400):
        df = _load_per_run(E1A / f"e1a_noinject_K{K}_runs.csv")
        if df is None:
            continue
        print(f"\nK={K}ms (clean-mechanistic prediction N_safe ≈ {10000 // K}):")
        print(f"  {'N':>6}  {'p_fail':>7}  {'CI_lo':>6}  {'CI_hi':>6}  {'runs':>5}")
        for N, nf, nt, pf, lo, hi in sorted(_pn_table(df, ("N",))):
            print(f"  {int(N):>6}  {pf:>7.1%}  {lo:>6.1%}  {hi:>6.1%}  {nt:>5}")
        n10 = _n10(df)
        print(f"  → N_10 = {n10}")
        if n10:
            pts.append((float(K), float(n10)))
    if len(pts) >= 2:
        K_v, N_v = zip(*pts)
        slope, intercept, r, _, se = sp.linregress(np.log(K_v), np.log(N_v))
        c = -slope
        ci = sp.t.ppf(0.975, len(pts) - 2) * se if len(pts) > 2 else float("nan")
        print(f"\n  No-injection K-exponent c = {c:.3f}"
              + (f"  95% CI = [{c-ci:.3f}, {c+ci:.3f}]" if len(pts) > 2 else "  (2 points — no CI)")
              + f"   r = {r:.4f}")
        print(f"  Idiomatic (injection on) c = 0.880; clean-mechanistic c = 1.0")
        print(f"  → {'moves toward 1.0 — injection explains the sub-linear 0.880 (Finding E1-7/A4)' if c > 0.94 else 'still sub-linear — injection is not the (sole) cause'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["a1", "a2", "a3", "a4"])
    args = ap.parse_args()
    print("=" * 64)
    print("SQ1 ENHANCEMENT ANALYSIS (A1–A4)")
    print("=" * 64)
    if args.only in (None, "a1"):
        analyse_a1()
    if args.only in (None, "a2"):
        analyse_a2()
    if args.only in (None, "a3"):
        analyse_a3()
    if args.only in (None, "a4"):
        analyse_a4()


if __name__ == "__main__":
    main()
