#!/usr/bin/env python3
"""Plots the handler-vs-DB-stop timing gap for ASP.NET and WebFlux."""
import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPO = Path(__file__).parent.parent.parent
FIGDIR = REPO / "experiments" / "sq2" / "figures"

GHOST_WF_S = 4.102
DB_STOP_ASP_S = 0.054

GREEN, RED, BLACK = "#2ca02c", "#d1495b", "#222222"


def main():
    os.makedirs(FIGDIR, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8.4, 4.2))

    y = 1
    ax.plot([0, DB_STOP_ASP_S], [y, y], color="0.8", lw=2, zorder=1)
    ax.scatter([DB_STOP_ASP_S], [y], marker="o", s=90, color=GREEN, zorder=5)
    ax.annotate("exception fires = DB stopped\n(OperationCanceledException ⟵ Postgres 57014)\n"
                "gap ≈ 0  →  verifiable from the exception chain",
                xy=(DB_STOP_ASP_S, y), xytext=(0.55, 1.30), fontsize=9, color=GREEN,
                arrowprops=dict(arrowstyle="->", color=GREEN, lw=1.2))

    y = 0
    ax.scatter([0], [y], marker="o", s=90, color=GREEN, zorder=5)
    ax.annotate("doOnCancel / doFinally fire\n(\"cancelled!\" — logs go green)",
                xy=(0, y), xytext=(0.05, 0.42), fontsize=9, color=GREEN,
                arrowprops=dict(arrowstyle="->", color=GREEN, lw=1.0))
    ax.barh(y, GHOST_WF_S, left=0, height=0.16, color=RED, alpha=0.85, zorder=3)
    ax.text(GHOST_WF_S / 2, y - 0.30,
            "handler believes IO stopped — it hasn't\nghost_holdtime ≈ 4.1 s  (all 5 operator layers, within 1 ms)",
            ha="center", va="top", fontsize=9, color=RED)
    ax.scatter([GHOST_WF_S], [y], marker="X", s=120, color=BLACK, zorder=6)
    ax.annotate("DB actually stops\n(query ran to completion — no CancelRequest)",
                xy=(GHOST_WF_S, y), xytext=(2.9, 0.52), fontsize=9, color=BLACK,
                arrowprops=dict(arrowstyle="->", color=BLACK, lw=1.0))

    ax.set_yticks([0, 1])
    ax.set_yticklabels(["WebFlux\n(reactive / R2DBC)", "ASP.NET\n(cooperative / Npgsql)"], fontsize=10)
    ax.set_ylim(-0.7, 1.7)
    ax.set_xlim(-0.15, 4.6)
    ax.set_xlabel("Time since client disconnect (s)")
    ax.set_title("SQ2 — the verifiability gap: when the handler fires vs when the DB actually stops\n"
                 "(cooperative = completion event, gap≈0; reactive = notification, ~4.1 s early)")
    ax.grid(True, axis="x", alpha=0.25)
    ax.spines[["top", "right", "left"]].set_visible(False)

    for ext in ("png", "pdf"):
        out = FIGDIR / f"e2_verifiability_gap.{ext}"
        fig.savefig(out, dpi=160, bbox_inches="tight")
        print(f"wrote {out.relative_to(REPO)}")


if __name__ == "__main__":
    main()
