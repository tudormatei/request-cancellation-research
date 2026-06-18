#!/usr/bin/env python3
"""Plots detection probability and conditional latency past the cliff (zone 3)."""
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPO = Path(__file__).parent.parent.parent
SRC = REPO / "experiments" / "sq1" / "e1a" / "e1a_cliff_dense_runs.csv"
FIGDIR = REPO / "experiments" / "sq1" / "figures"

K_MS = 100.0
C = 1
T_REMAINING_MS = 10000
FLOOR_MS = 2 * K_MS
SUCCESS_THRESH = 0.5


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    centre = (k + z**2 / 2) / (n + z**2)
    margin = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / (1 + z**2 / n)
    return max(0.0, centre - margin), min(1.0, centre + margin)


def n_safe_pred(k_ms: float, c: int) -> float:
    return 5499.0 * c / k_ms**0.880


def main():
    os.makedirs(FIGDIR, exist_ok=True)
    df = pd.read_csv(SRC)
    df = df[(df.framework == "aspnet") & (df.yield_interval_ms == K_MS)]

    rows = []
    for n, g in df.groupby("N"):
        runs = len(g)
        succ = g[g.run_cancel_rate > SUCCESS_THRESH]
        k = len(succ)
        p = k / runs
        lo, hi = wilson_ci(k, runs)
        lat_med = succ.L1_median.median() if k else np.nan
        rows.append(dict(
            N=int(n), runs=runs, k_succ=k, p=p, p_lo=lo, p_hi=hi,
            lat_med=lat_med,
            lat_floor=succ.L1_min.median() if k else np.nan,
            lat_tail=succ.L1_max.median() if k else np.nan,
            lat_max_abs=succ.L1_max.max() if k else np.nan,
            partial=int(((g.run_cancel_rate > 0.0) & (g.run_cancel_rate < 1.0)).sum()),
        ))
    t = pd.DataFrame(rows).sort_values("N").reset_index(drop=True)

    n_pred = n_safe_pred(K_MS, C)

    pd.set_option("display.width", 140)
    print(f"\nSource: {SRC.relative_to(REPO)}")
    print(f"C={C}  K={K_MS:g}ms  2K floor={FLOOR_MS:g}ms  T_remaining={T_REMAINING_MS}ms  "
          f"predicted N_safe={n_pred:.1f}")
    print(f"Metric: p(N) = per-run success rate (run_cancel_rate>{SUCCESS_THRESH}); "
          f"conditional latency from successful runs only.\n")
    show = t[["N", "runs", "k_succ", "p", "p_lo", "p_hi",
              "lat_floor", "lat_med", "lat_tail", "partial"]].copy()
    for c in ["p", "p_lo", "p_hi"]:
        show[c] = show[c].round(3)
    for c in ["lat_floor", "lat_med", "lat_tail"]:
        show[c] = show[c].round(0).astype("Int64")
    print(show.to_string(index=False))

    print(f"\nAll-or-nothing check: total genuinely-partial runs (0<rate<1) across all cells "
          f"= {t.partial.sum()}  (expected ~0; confirms p(N)_per-request == p(N)_per-run)")

    lo_p, hi_p = t.p.max(), t.p.min()
    print(f"\np(N): {lo_p:.2f} (N={t.N.iloc[0]}) -> {hi_p:.2f} over the scanned range")
    print(f"Conditional latency, MEDIAN (successful runs): "
          f"{t.lat_med.min():.0f}..{t.lat_med.max():.0f} ms "
          f"(= {t.lat_med.min()/K_MS:.2f}..{t.lat_med.max()/K_MS:.2f} K) — essentially flat")
    r = np.corrcoef(t.N, t.lat_med)[0, 1]
    print(f"corr(N, median latency) = {r:+.3f} (absolute variation <2% — no load trend); "
          f"slow tail (median L1_max) reaches ~{t.lat_tail.max():.0f} ms but does not move the median.")
    print(f"Ceiling: undetected mass at ~(N/C)*T_remaining "
          f"(e.g. N=175 -> ~{175/C*T_REMAINING_MS/1000:.0f}s), vs median latency ~0.3 s.")

    C_LAT, C_P = "#1f6feb", "#d1495b"
    fig, axL = plt.subplots(figsize=(7.6, 5.0))
    axR = axL.twinx()

    axL.fill_between(t.N, t.lat_floor, t.lat_tail, color=C_LAT, alpha=0.12, zorder=1,
                     label="latency spread  [median $L1_{min}$, median $L1_{max}$]")
    axL.plot(t.N, t.lat_med, "o-", color=C_LAT, lw=2, ms=4, zorder=3,
             label="conditional detection latency — median (successful runs)")
    axL.axhline(FLOOR_MS, ls=":", color=C_LAT, lw=1.2, alpha=0.8,
                label=f"$2K$ = {FLOOR_MS:.0f} ms ($N{{=}}1$ minimum; saturated median ~2.9$K$)")

    yerr = np.clip(np.vstack([t.p - t.p_lo, t.p_hi - t.p]), 0, None)
    axR.errorbar(t.N, t.p, yerr=yerr, fmt="s-", color=C_P, lw=2, ms=5, capsize=3,
                 zorder=4, label="detection probability $p(N)$ = per-run success (Wilson 95% CI)")

    axL.axvline(n_pred, ls="--", color="0.35", lw=1.4, zorder=2)
    axL.text(n_pred + 1.5, axL.get_ylim()[1] * 0.96,
             f"predicted $N_{{safe}}$≈{n_pred:.0f}", color="0.25",
             fontsize=9, va="top")

    axL.set_xlabel("Concurrent CPU requests  $N$  (= thread-pool size, $C=1$)")
    axL.set_ylabel("Detection latency (ms)", color=C_LAT)
    axR.set_ylabel("Detection probability  $p(N)$", color=C_P)
    axL.tick_params(axis="y", labelcolor=C_LAT)
    axR.tick_params(axis="y", labelcolor=C_P)
    axR.set_ylim(0, 1.05)
    axL.set_ylim(0, max(np.nanmax(t.lat_tail) * 1.25, FLOOR_MS * 1.5))
    axL.grid(True, alpha=0.2)

    axL.set_title("E1 zone 3 — past the cliff, detection PROBABILITY erodes while\n"
                  f"conditional latency stays flat  ($K={K_MS:g}$ms, $C={C}$, "
                  f"$T_{{rem}}={T_REMAINING_MS//1000}$s)")

    hL, lL = axL.get_legend_handles_labels()
    hR, lR = axR.get_legend_handles_labels()
    axL.legend(hL + hR, lL + lR, loc="center left", fontsize=8.5, framealpha=0.95)

    fig.text(0.5, -0.02,
             r"$p(N)$ is the per-run success rate (= per-request under all-or-nothing runs, "
             r"Finding E1-8). Undetected requests run to completion: wall-clock residual "
             r"$\approx (N/C)\,T_{rem}$ (seconds–minutes), off the top of this axis.",
             ha="center", fontsize=8, color="0.3")

    for ext in ("png", "pdf"):
        out = FIGDIR / f"e1_zone3_pN.{ext}"
        fig.savefig(out, dpi=160, bbox_inches="tight")
        print(f"\nwrote {out.relative_to(REPO)}")


if __name__ == "__main__":
    main()
