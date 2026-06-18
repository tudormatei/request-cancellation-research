#!/usr/bin/env python3
"""Renders the SQ1 master summary figure (detection latency + reliability panels)."""
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPO = Path(__file__).parent.parent.parent
E1A = REPO / "experiments" / "sq1" / "e1a"
E1B = REPO / "experiments" / "sq1" / "e1b"
FIGDIR = REPO / "experiments" / "sq1" / "figures"

K_MS = 100.0
C = 1
SUCCESS = 0.5


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    centre = (k + z**2 / 2) / (n + z**2)
    margin = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / (1 + z**2 / n)
    return max(0.0, centre - margin), min(1.0, centre + margin)


def n_safe_pred(k_ms: float, c: int) -> float:
    return 5499.0 * c / k_ms**0.880


def per_run_pN(path: Path, framework: str | None = None, K: float | None = None):
    """Return (N[], p[], lo[], hi[]) from a per-run CSV using the SQ1 per-run metric + W1-6 filter."""
    if not path.exists():
        return None
    df = pd.read_csv(path)
    if framework is not None and "framework" in df:
        df = df[df.framework == framework]
    if K is not None and "yield_interval_ms" in df:
        df = df[df.yield_interval_ms == K]
    df = df[df.n_requests <= df.N]
    Ns, ps, los, his = [], [], [], []
    for n, g in df.groupby("N"):
        runs = len(g)
        k = int((g.run_cancel_rate > SUCCESS).sum())
        lo, hi = wilson_ci(k, runs)
        Ns.append(int(n)); ps.append(k / runs); los.append(lo); his.append(hi)
    order = np.argsort(Ns)
    return (np.array(Ns)[order], np.array(ps)[order],
            np.array(los)[order], np.array(his)[order])


def summary_pN(path: Path, framework: str):
    """Fallback p(N) from a summary CSV (cancel_rate + n_requests), Wilson CI per cell."""
    if not path.exists():
        return None
    df = pd.read_csv(path)
    df = df[df.framework == framework].sort_values("N")
    Ns, ps, los, his = [], [], [], []
    for _, r in df.iterrows():
        k, n = int(r.n_cancelled), int(r.n_requests)
        lo, hi = wilson_ci(k, n)
        Ns.append(int(r.N)); ps.append(r.cancel_rate); los.append(lo); his.append(hi)
    return np.array(Ns), np.array(ps), np.array(los), np.array(his)


def _band(ax, x, p, lo, hi, color, label, marker="o"):
    yerr = np.clip(np.vstack([p - lo, hi - p]), 0, None)
    ax.errorbar(x, p, yerr=yerr, fmt=f"{marker}-", color=color, lw=2, ms=5,
                capsize=2.5, label=label, zorder=3)


def main():
    os.makedirs(FIGDIR, exist_ok=True)
    fig, (axT, axB) = plt.subplots(2, 1, figsize=(8.2, 9.2),
                                   gridspec_kw=dict(height_ratios=[1, 1.25]))

    COL = {"aspnet": "#1f6feb", "webflux": "#2ca02c", "go": "#9467bd"}
    lat = E1B / "e1b_latency_sweep.csv"
    drew_lat = False
    if lat.exists():
        d = pd.read_csv(lat)
        for fw, lbl in [("aspnet", "ASP.NET — saturated (pool full): ~2K"),
                        ("webflux", "WebFlux / boundedElastic: flat ~1 ms")]:
            s = d[d.framework == fw].sort_values("yield_interval_ms")
            if len(s):
                axT.plot(s.yield_interval_ms, s.L1_median, "o-", color=COL[fw],
                         lw=2, ms=5, label=lbl)
                drew_lat = True
        ks = np.array(sorted(d.yield_interval_ms.unique()), float)
        axT.plot(ks, 2 * ks, ":", color=COL["aspnet"], lw=1.3, alpha=0.7,
                 label="$2K$ reference")
    hp = E1B / "e1b_headroom_probe.csv"
    if hp.exists():
        hd = pd.read_csv(hp)
        hmin = hd.L1_median.min()
        axT.axhspan(max(hmin, 0.5), 3, color="#1f6feb", alpha=0.08, zorder=0)
        axT.text(axT.get_xlim()[1] if drew_lat else 400, 2.0,
                 "ASP.NET headroom regime (spare worker) ~1 ms",
                 fontsize=8, color=COL["aspnet"], va="bottom", ha="right")
    axT.set_xscale("log"); axT.set_yscale("log")
    axT.set_xlabel("Yield / poll interval  $K$  (ms)")
    axT.set_ylabel("Detection latency  $L_1$ (ms, median)")
    axT.set_title("Detection latency: cooperative & reactive are indistinguishable (~1 ms)\n"
                  "until the pool saturates — then ASP.NET jumps to ~2K, WebFlux stays flat")
    axT.grid(True, which="both", alpha=0.2)
    if drew_lat:
        axT.legend(fontsize=8.5, loc="upper left")

    npred = n_safe_pred(K_MS, C)

    asp = per_run_pN(E1A / "e1a_cliff_dense_runs.csv", framework="aspnet", K=K_MS)
    if asp:
        _band(axB, *asp, color="#d1495b", label="ASP.NET cooperative pool — CLIFF", marker="s")

    be = per_run_pN(E1A / "e1f_webflux_be_runs.csv", framework="webflux")
    if be is None:
        be = summary_pN(E1A / "e1a_cpu.csv", "webflux")
        be_lbl = "WebFlux / boundedElastic — flat ~100% (e1a_cpu)"
    else:
        be_lbl = "WebFlux / boundedElastic — flat ~100% (A1)"
    if be:
        _band(axB, *be, color="#2ca02c", label=be_lbl, marker="o")

    imm = per_run_pN(E1A / "e1f_webflux_imm_runs.csv", framework="webflux")
    if imm:
        _band(axB, *imm, color="#8c564b",
              label="WebFlux / immediate (probe) — BLACKOUT", marker="v")

    go = per_run_pN(E1A / "e1g_go_cliff_runs.csv", framework="go", K=K_MS)
    if go:
        _band(axB, *go, color="#9467bd", label="Go cooperative token (K=100ms)", marker="D")

    xmax = 200
    if asp:
        xmax = max(xmax, int(asp[0].max()))
    axB.plot([1, xmax], [0, 0], "--", color="0.45", lw=1.6,
             label="Spring MVC passive — 0% always (architectural)")

    axB.axvline(npred, ls="--", color="0.35", lw=1.3)
    axB.text(npred + 2, 0.5, f"predicted $N_{{safe}}$≈{npred:.0f}\n(ASP.NET, $K$=100ms, $C$=1)",
             color="0.25", fontsize=8.5, va="center")
    axB.set_xlabel("Concurrent CPU requests  $N$")
    axB.set_ylabel("Detection probability  $p(N)$  (per-run, Wilson 95% CI)")
    axB.set_ylim(-0.05, 1.08)
    axB.grid(True, alpha=0.2)
    axB.set_title("Detection reliability under load: the carrier of the abort decides\n"
                  "(detection survives load iff its delivery context can't be starved by the work)")
    axB.legend(fontsize=8.5, loc="center right", framealpha=0.95)

    fig.tight_layout()
    for ext in ("png", "pdf"):
        out = FIGDIR / f"e1_master.{ext}"
        fig.savefig(out, dpi=160, bbox_inches="tight")
        print(f"wrote {out.relative_to(REPO)}")

    drawn = ["ASP.NET cliff" if asp else None,
             "WebFlux/be" if be else None,
             "WebFlux/immediate" if imm else None,
             "Go" if go else None]
    print("Carriers drawn:", [d for d in drawn if d] + ["Spring MVC (floor)"])
    if not imm or not go:
        print("NOTE: re-run after the A1/A2 supervisor data lands to add the missing carriers.")


if __name__ == "__main__":
    main()
