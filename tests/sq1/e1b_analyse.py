#!/usr/bin/env python3
"""Analyses E1b detection-latency sweep data."""

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sp

REPO = Path(__file__).parent.parent.parent
DATA = REPO / "experiments" / "sq1" / "e1b"
K_MS = 100


def log_log_regression(x: list[float], y: list[float]) -> tuple[float, float, float, float]:
    lx, ly = np.log(x), np.log(y)
    slope, intercept, r, p, se = sp.linregress(lx, ly)
    n = len(x)
    t_crit = sp.t.ppf(0.975, n - 2)
    ci_half = t_crit * se
    return float(slope), float(r), float(slope - ci_half), float(slope + ci_half)


def analyse_latency_sweep(df: pd.DataFrame) -> None:
    print("\n── Latency sweep (K parametric, N=1, T_max=1) ──")
    asp = df[df["framework"] == "aspnet"].sort_values("yield_interval_ms")
    print(f"\n{'K_ms':>6}  {'L1_min':>8}  {'L1_mean':>8}  {'2×K':>6}  {'err%':>6}")
    print("─" * 45)
    for _, r in asp.iterrows():
        K = int(r["yield_interval_ms"])
        pred = 2 * K
        err = (r["L1_mean"] - pred) / pred * 100
        print(f"{K:>6}  {r['L1_min']:>8.1f}  {r['L1_mean']:>8.1f}  {pred:>6}  {err:>+6.1f}%")

    K_vals = asp["yield_interval_ms"].astype(float).tolist()
    L1_vals = asp["L1_mean"].tolist()
    slope, r_val, ci_lo, ci_hi = log_log_regression(K_vals, L1_vals)
    print(f"\nLog-log regression: slope={slope:.3f}  95% CI=[{ci_lo:.3f}, {ci_hi:.3f}]")
    r_pearson, _ = sp.pearsonr(np.log(K_vals), np.log(L1_vals))
    print(f"Pearson r = {r_pearson:.4f}")
    if 0.9 <= slope <= 1.1 and r_pearson > 0.999:
        print("✓ L1 ∝ K_ms confirmed — formula L1_min = 2×K_ms validated")
    else:
        print("✗ Slope or r outside expected range — investigate")

    print("\nWebFlux vs ASP.NET comparison:")
    for fw in df["framework"].unique():
        sub = df[df["framework"] == fw].sort_values("yield_interval_ms")
        print(f"  {fw}: L1_mean = {sub['L1_mean'].tolist()}")


def analyse_tmax_sweep(df: pd.DataFrame) -> None:
    print(f"\n── T_max sweep (K={K_MS}ms, N=8) ──")
    asp = df[df["framework"] == "aspnet"].sort_values("T")
    pred_bound = 2 * K_MS
    print(f"\n{'T_max':>6}  {'L1_min':>7}  {'L1_median':>9}  {'L1_max':>7}  {'rate':>6}")
    print("─" * 43)
    for _, r in asp.iterrows():
        print(f"{int(r['T']):>6}  {r['L1_min']:>7.1f}  {r['L1_median']:>9.1f}  "
              f"{r['L1_max']:>7.1f}  {r['cancel_rate']:>6.1%}")

    T_vals = asp["T"].astype(float).tolist()
    med_vals = asp["L1_median"].tolist()
    r_sp, p_sp = sp.spearmanr(T_vals, med_vals)
    print(f"\nSpearman r(T_max, L1_median) = {r_sp:.3f}  p = {p_sp:.4f}")

    all_in_range = all(pred_bound * 0.9 <= m <= pred_bound * 1.1 for m in med_vals)
    print(f"All medians in [2K ± 10%] = [{pred_bound*0.9:.0f}, {pred_bound*1.1:.0f}]ms: "
          f"{'YES' if all_in_range else 'NO'}")

    if p_sp > 0.10 and all_in_range:
        print("✓ Pre-registered criteria met — L1 is K_ms-only at leading order")
    else:
        print("✗ Criteria failed — see relaxed claim:")
        span = max(med_vals) / min(med_vals)
        print(f"  L1_median range: [{min(med_vals):.1f}, {max(med_vals):.1f}]ms "
              f"({span:.2f}× span, within {(max(med_vals)/pred_bound - 1)*100:.0f}% of 2K)")


def main() -> None:
    latency_path = DATA / "e1b_latency_sweep.csv"
    tmax_path = DATA / "e1b_tmax_sweep.csv"

    print("=" * 60)
    print("E1b — Detection Latency Formula")
    print("=" * 60)

    if latency_path.exists():
        analyse_latency_sweep(pd.read_csv(latency_path))
    else:
        print(f"\nMissing: {latency_path}  (run scripts/sq1/e1b_run.sh first)")

    if tmax_path.exists():
        analyse_tmax_sweep(pd.read_csv(tmax_path))
    else:
        print(f"\nMissing: {tmax_path}  (run scripts/sq1/e1b_run.sh first)")


if __name__ == "__main__":
    main()
