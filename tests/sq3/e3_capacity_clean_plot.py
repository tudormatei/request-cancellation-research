#!/usr/bin/env python3
"""Plots measured E3 sustainable capacity X_max vs pool size."""
from pathlib import Path
import csv
import numpy as np
import matplotlib.pyplot as plt

REPO = Path(__file__).parent.parent.parent
XMAX = REPO / "experiments" / "sq3" / "e3c" / "e3_capacity_xmax.csv"
OUT = REPO / "experiments" / "sq3" / "figures"
OUT.mkdir(parents=True, exist_ok=True)

rows = list(csv.DictReader(XMAX.open()))
d = {}
for r in rows:
    d.setdefault(r["framework"], []).append((int(r["pool"]), float(r["X_max"])))
asp = sorted(d["aspnet"]); wf = sorted(d["webflux"])
ap, ax_ = np.array([p for p, _ in asp]), np.array([x for _, x in asp])
wp, wx = np.array([p for p, _ in wf]), np.array([x for _, x in wf])

slope0 = lambda x, y: float(np.sum(x * y) / np.sum(x * x))
m_asp, m_wf = slope0(ap, ax_), slope0(wp, wx)

plt.rcParams.update({"font.size": 11, "axes.linewidth": 0.8})
fig, ax = plt.subplots(figsize=(5.0, 3.4))
xs = np.linspace(0, 44, 50)
CA, CW = "#1f77b4", "#d62728"
ax.plot(xs, m_asp * xs, "--", lw=1.1, color=CA, alpha=0.7, zorder=1)
ax.plot(xs, m_wf * xs, "--", lw=1.1, color=CW, alpha=0.7, zorder=1)
ax.plot(ap, ax_, "o", color=CA, ms=6, label="ASP.NET (Npgsql)", zorder=3)
ax.plot(wp, wx, "s", color=CW, ms=6, label="WebFlux (R2DBC)", zorder=3)
ax.set_xlabel("Connection pool size")
ax.set_ylabel(r"Max sustainable rate $X_{\max}$ (req/s)")
ax.set_xlim(0, 44); ax.set_ylim(0, 18); ax.set_xticks([0, 10, 20, 30, 40])
ax.grid(True, ls=":", lw=0.6, alpha=0.6)
ax.legend(frameon=False, loc="upper left")
fig.tight_layout()

fig.canvas.draw()
def disp_angle(slope):
    p0 = ax.transData.transform((0, 0)); p1 = ax.transData.transform((10, slope * 10))
    return np.degrees(np.arctan2(p1[1] - p0[1], p1[0] - p0[0]))
for slope, col, xpos in [(m_asp, CA, 31), (m_wf, CW, 33)]:
    ax.text(xpos, slope * xpos + 0.45, f"slope $\\approx$ {slope:.2f}", color=col, fontsize=10,
            rotation=disp_angle(slope), rotation_mode="anchor", ha="center", va="bottom")
for e in ("png", "pdf"):
    fig.savefig(OUT / f"e3_capacity_measured.{e}", dpi=200, bbox_inches="tight")
print(f"ASP.NET slope={m_asp:.3f}  WebFlux slope={m_wf:.3f}  slope-ratio={m_asp/m_wf:.2f}")
print("wrote", OUT / "e3_capacity_measured.png")
