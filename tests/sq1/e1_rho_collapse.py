#!/usr/bin/env python3
"""Tests whether per-run detection-failure probability collapses onto one curve in rho = N/N_safe."""
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy import stats as sp

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPO = Path(__file__).parent.parent.parent
DATA = REPO / "experiments" / "sq1" / "e1a"
FIGDIR = REPO / "experiments" / "sq1" / "figures"

CONFIGS = [
    ("e1a_cliff_dense_runs.csv",      1, 100, None),
    ("e1a_cliff_K_dense_K200_runs.csv", 1, 200, None),
    ("e1a_cliff_K_dense_K500_runs.csv", 1, 500, None),
    ("e1a_cliff_C_dense_C2_runs.csv",   2, 100, 2),
    ("e1a_cliff_C_dense_C4_runs.csv",   4, 100, 4),
]


def n_safe(C, K):
    return 5499.0 * C / K**0.880


def wilson_ci(k, n, z=1.96):
    if n == 0:
        return 0.0, 1.0
    p = k / n
    c = (k + z**2 / 2) / (n + z**2)
    m = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / (1 + z**2 / n)
    return max(0.0, c - m), min(1.0, c + m)


def nll(params, rho, nf, nt):
    b0, b1 = params
    z = np.clip(b0 + b1 * rho, -30, 30)
    p = 1.0 / (1.0 + np.exp(-z))
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return -np.sum(nf * np.log(p) + (nt - nf) * np.log(1 - p))


def fit(rho, nf, nt, x0=(-3.0, 2.0)):
    r = minimize(nll, x0, args=(rho, nf, nt), method="Nelder-Mead",
                 options=dict(xatol=1e-6, fatol=1e-6, maxiter=10000))
    return r.x, r.fun


def main():
    os.makedirs(FIGDIR, exist_ok=True)
    rows = []
    for fname, C, K, cal in CONFIGS:
        df = pd.read_csv(DATA / fname)
        asp = df[df["framework"] == "aspnet"].copy()
        asp = asp[asp["n_requests"] <= asp["N"]]
        asp["failed"] = (asp["n_cancelled"] == 0).astype(int)
        for N, g in asp.groupby("N"):
            if cal is not None and N == cal:
                continue
            nt = len(g)
            nf = int(g["failed"].sum())
            lo, hi = wilson_ci(nf, nt)
            rows.append(dict(config=f"C{C}/K{K}", C=C, K=K, N=int(N),
                             rho=N / n_safe(C, K), nf=nf, nt=nt,
                             p=nf / nt, lo=lo, hi=hi))
    t = pd.DataFrame(rows).sort_values(["C", "K", "N"]).reset_index(drop=True)

    pd.set_option("display.width", 160)
    print("\nPer-cell per-run failure (W1-6-filtered), normalised to rho = N / N_safe(C,K):")
    show = t.copy()
    for c in ["rho", "p", "lo", "hi"]:
        show[c] = show[c].round(3)
    print(show[["config", "N", "rho", "nf", "nt", "p", "lo", "hi"]].to_string(index=False))

    rho, nf, nt = t.rho.values, t.nf.values.astype(float), t.nt.values.astype(float)
    (pb0, pb1), pooled_nll = fit(rho, nf, nt)

    per_nll = 0.0
    per_params = {}
    for cfg, g in t.groupby("config"):
        (b0, b1), nllc = fit(g.rho.values, g.nf.values.astype(float), g.nt.values.astype(float))
        per_params[cfg] = (b0, b1)
        per_nll += nllc

    n_cfg = t.config.nunique()
    LR = 2 * (pooled_nll - per_nll)
    df_lr = 2 * (n_cfg - 1)
    pval = sp.chi2.sf(LR, df_lr)

    print("\n" + "═" * 64)
    print("COLLAPSE TEST — is p_fail a function of rho alone?")
    print("═" * 64)
    print(f"  pooled logistic:   logit(p_fail) = {pb0:+.3f} {pb1:+.3f}·rho   (NLL={pooled_nll:.2f})")
    for cfg, (b0, b1) in per_params.items():
        print(f"    {cfg:>8}:  b0={b0:+.2f}  b1={b1:+.2f}")
    print(f"  per-config total NLL = {per_nll:.2f}")
    print(f"  LR = 2·ΔNLL = {LR:.2f},  df = {df_lr},  p = {pval:.3f}")
    if pval > 0.05:
        print("  → per-config model NOT a significant improvement (p>0.05):")
        print("    p_fail(rho) COLLAPSES — one universal curve over the tested C,K.")
    else:
        print("  → per-config model IS a significant improvement (p≤0.05):")
        print("    the shape depends on C/K too — no clean universal collapse.")

    def pf(r):
        z = pb0 + pb1 * r
        return 1.0 / (1.0 + np.exp(-z))
    print("\nPooled-curve lookup  p_fail(rho):")
    for r in (1.0, 1.1, 1.2, 1.5, 2.0):
        print(f"  rho={r:>4}: p_fail ≈ {pf(r)*100:4.1f}%"
              + ("   (rho>data range — extrapolation)" if r > t.rho.max() else ""))
    print(f"\n(data span: rho ∈ [{t.rho.min():.2f}, {t.rho.max():.2f}])")

    colors = {"C1/K100": "#1f6feb", "C1/K200": "#2a9d8f", "C1/K500": "#8e44ad",
              "C2/K100": "#e76f51", "C4/K100": "#d1495b"}
    fig, ax = plt.subplots(figsize=(7.8, 5.2))
    for cfg, g in t.groupby("config"):
        yerr = np.vstack([g.p - g.lo, g.hi - g.p])
        ax.errorbar(g.rho, g.p, yerr=yerr, fmt="o", color=colors.get(cfg, "0.4"),
                    ms=5, capsize=2.5, lw=1, alpha=0.9, label=cfg)
    rr = np.linspace(t.rho.min(), max(t.rho.max(), 2.0), 200)
    ax.plot(rr, pf(rr), "-", color="black", lw=2,
            label=f"pooled logistic  (collapse p={pval:.2f})")
    ax.axvline(1.0, ls=":", color="0.5", lw=1)
    ax.text(1.01, 0.46, "$N_{safe}$\n(formula)", color="0.4", fontsize=8, va="top")
    ax.axhline(0.10, ls=":", color="0.5", lw=1)
    ax.set_xlabel(r"Oversubscription  $\rho = N / N_{safe}(C,K)$,   "
                  r"$N_{safe}=5499\,C/K^{0.88}$")
    ax.set_ylabel("Per-run detection-failure probability  $p_{fail}$")
    ax.set_title("E1 — failure probability vs normalised oversubscription\n"
                 "(does the cliff collapse onto one curve across $C$ and $K$?)")
    ax.set_ylim(-0.02, 0.6)
    ax.grid(True, alpha=0.2)
    ax.legend(loc="upper left", fontsize=8.5, framealpha=0.95, ncol=2)

    for ext in ("png", "pdf"):
        out = FIGDIR / f"e1_rho_collapse.{ext}"
        fig.savefig(out, dpi=160, bbox_inches="tight")
        print(f"wrote {out.relative_to(REPO)}")


if __name__ == "__main__":
    main()
