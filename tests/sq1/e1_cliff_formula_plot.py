#!/usr/bin/env python3
"""Plots the cliff-location power-law fit (N_safe vs K)."""
import os
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPO = Path(__file__).parent.parent.parent
FIGDIR = REPO / "experiments" / "sq1" / "figures"

FIT = [(50, 175), (100, 95), (150, 66), (200, 55), (400, 25), (500, 25)]
ALPHA, C_EXP = 5499.0, 0.880
BLIND_K, BLIND_NSAFE, BLIND_C = 300, 73, 2


def main():
    os.makedirs(FIGDIR, exist_ok=True)
    K = np.array([k for k, _ in FIT], float)
    N = np.array([n for _, n in FIT], float)

    fig, ax = plt.subplots(figsize=(7.6, 5.2))
    kk = np.logspace(np.log10(40), np.log10(560), 200)
    ax.plot(kk, ALPHA / kk**C_EXP, "-", color="#1f6feb", lw=2,
            label=r"fit:  $N_{safe}/C = 5499 \, / \, K_{ms}^{0.880}$")
    ax.scatter(K, N, s=70, color="#1f6feb", zorder=5,
               label="measured cliff $N_{10}$  (C=1, 6 poll intervals — in-sample)")

    ax.scatter([BLIND_K], [BLIND_NSAFE / BLIND_C], marker="*", s=320, color="#d1495b",
               edgecolor="k", linewidth=0.6, zorder=6,
               label=f"BLIND  C=2, K=300ms → measured {BLIND_NSAFE}/2 = {BLIND_NSAFE/BLIND_C:.1f}  (line: {ALPHA/BLIND_K**C_EXP:.1f})")
    ax.annotate("predicted 73, measured 73\n(0% error, out-of-sample)",
                xy=(BLIND_K, BLIND_NSAFE / BLIND_C), xytext=(150, 17),
                fontsize=9, color="#d1495b",
                arrowprops=dict(arrowstyle="->", color="#d1495b", lw=1.2))

    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("Poll / yield interval  $K$  (ms)")
    ax.set_ylabel("Cliff location per core  $N_{safe}/C$")
    ax.set_title("The cancellation cliff follows a power law in K\n"
                 "(sub-linear exponent 0.880; blind C×K point lands on the line)")
    ax.grid(True, which="both", alpha=0.25)
    ax.legend(fontsize=9, loc="upper right")

    for ext in ("png", "pdf"):
        out = FIGDIR / f"e1_cliff_formula.{ext}"
        fig.savefig(out, dpi=160, bbox_inches="tight")
        print(f"wrote {out.relative_to(REPO)}")


if __name__ == "__main__":
    main()
