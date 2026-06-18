#!/usr/bin/env python3
"""Analyses the E1a cliff data (existence, causal check, and formula fit)."""

import argparse
import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sp

REPO = Path(__file__).parent.parent.parent
DATA = REPO / "experiments" / "sq1" / "e1a"


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    centre = (k + z**2 / 2) / (n + z**2)
    margin = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / (1 + z**2 / n)
    return max(0.0, centre - margin), min(1.0, centre + margin)


def strict_n_safe(group: pd.DataFrame) -> int | None:
    g = group.sort_values("N")
    n_safe = None
    for _, row in g.iterrows():
        lo, _ = wilson_ci(int(row["n_cancelled"]), int(row["n_requests"]))
        if lo >= 0.95:
            n_safe = int(row["N"])
        else:
            break
    return n_safe


def rate_table(df: pd.DataFrame, label: str = "") -> None:
    if label:
        print(f"\n{label}")
    print(f"{'N':>6}  {'K_ms':>5}  {'framework':>12}  {'rate':>6}  {'CI_lo':>6}  {'CI_hi':>6}  {'n_req':>6}")
    print("─" * 60)
    for _, row in df.sort_values(["yield_interval_ms", "N", "framework"]).iterrows():
        k, n = int(row["n_cancelled"]), int(row["n_requests"])
        lo, hi = wilson_ci(k, n)
        K = int(row["yield_interval_ms"]) if pd.notna(row.get("yield_interval_ms")) else "-"
        print(f"{int(row['N']):>6}  {K:>5}  {row['framework']:>12}  "
              f"{row['cancel_rate']:>6.1%}  {lo:>6.1%}  {hi:>6.1%}  {n:>6}")



def analyse_causal(cpu_df: pd.DataFrame, async_df: pd.DataFrame) -> None:
    print("\n" + "═" * 60)
    print("CAUSAL — cliff exists, thread occupancy is the variable")
    print("═" * 60)

    rate_table(cpu_df, "CPU scenario:")
    rate_table(async_df, "Async scenario:")

    asp_cpu = cpu_df[cpu_df["framework"] == "aspnet"].sort_values("N")
    n_low = asp_cpu[asp_cpu["cancel_rate"] == 1.0]["N"].max()
    first_drop = asp_cpu[asp_cpu["cancel_rate"] < 1.0]
    if pd.notna(n_low):
        if len(first_drop):
            fd = first_drop.iloc[0]
            print(f"\nCliff (ASP.NET, cpu): 100% up to N={int(n_low)}; first drop at "
                  f"N={int(fd['N'])} (rate {fd['cancel_rate']:.0%}). Min rate in range: "
                  f"{asp_cpu['cancel_rate'].min():.0%} (this coarse causal scan does not reach 0%; "
                  f"the per-run cliff sigmoid is Findings E1-7/E1-8).")
        else:
            print(f"\nNo cliff in tested range (100% to N={int(n_low)}).")

    print("\nTwo-scenario comparison (ASP.NET, cpu vs async at matched N):")
    cpu_idx = cpu_df[cpu_df["framework"] == "aspnet"].set_index("N")
    asn_idx = async_df[async_df["framework"] == "aspnet"].set_index("N")
    shared = sorted(set(cpu_idx.index) & set(asn_idx.index))
    if shared:
        print(f"{'N':>6}  {'cpu':>8}  {'async':>8}")
        for n in shared:
            print(f"{n:>6}  {cpu_idx.loc[n,'cancel_rate']:>8.1%}  {asn_idx.loc[n,'cancel_rate']:>8.1%}")



def analyse_nsweep(df: pd.DataFrame) -> None:
    print("\n" + "═" * 60)
    print("N-SWEEP — L1 N-independence and cliff location (K=100ms)")
    print("═" * 60)
    asp = df[df["framework"] == "aspnet"].sort_values("N")
    rate_table(asp)
    stable_rows = []
    for _, row in asp.iterrows():
        if row["cancel_rate"] >= 0.999:
            stable_rows.append(row)
        else:
            break
    stable = pd.DataFrame(stable_rows)
    if len(stable) >= 3:
        r, p = sp.spearmanr(stable["N"], stable["L1_median"])
        spread = stable["L1_median"].max() / stable["L1_median"].min()
        print(f"\nStable zone N∈[{int(stable.N.min())},{int(stable.N.max())}] (pre-cliff, 100% rate):")
        print(f"  Spearman r(N, L1_median) = {r:.3f}  p={p:.4f};  L1 spread = {spread:.2f}×")
        if spread < 1.5:
            print(f"  ✓ L1 practically N-independent (spread {spread:.2f}× — vs ~35× for "
                  f"iteration-based code); any rank correlation is statistically detectable but "
                  f"practically negligible.")
        else:
            print("  ✗ L1 varies materially with N — investigate")



def analyse_cliff_scan(df: pd.DataFrame) -> None:
    print("\n" + "═" * 60)
    print("CLIFF-SCAN — rough local √K check (SUPERSEDED by kc-formula K^0.880; √K is rejected below)")
    print("═" * 60)
    asp = df[df["framework"] == "aspnet"]
    rate_table(asp)

    results = []
    for K, grp in asp.groupby("yield_interval_ms"):
        n_s = strict_n_safe(grp)
        product = n_s * math.sqrt(K) if n_s else None
        label = f"N_safe={n_s}  N×√K={product:.0f}" if product else "cliff not reached"
        print(f"\n  K={int(K):>3}ms: {label}")
        if product:
            results.append((K, n_s, product))

    if len(results) >= 2:
        products = [p for _, _, p in results]
        spread = (max(products) - min(products)) / max(products)
        print(f"\nN×√K constant within {spread:.0%} → "
              f"{'✓ formula consistent' if spread < 0.25 else '✗ not constant'}")



def analyse_k_sweep(df: pd.DataFrame) -> None:
    print("\n" + "═" * 60)
    print("K-SWEEP — K-exponent c in N_safe ∝ K_ms^(-c)")
    print("═" * 60)
    asp = df[df["framework"] == "aspnet"]
    rate_table(asp)

    results = []
    for K, grp in asp.groupby("yield_interval_ms"):
        n_s = strict_n_safe(grp)
        print(f"  K={int(K):>3}ms: strict N_safe={n_s}")
        if n_s:
            results.append((float(K), float(n_s)))

    if len(results) >= 3:
        K_vals, N_vals = zip(*results)
        lx, ly = np.log(K_vals), np.log(N_vals)
        slope, intercept, _, _, se = sp.linregress(lx, ly)
        n = len(results)
        ci_half = sp.t.ppf(0.975, n - 2) * se
        c, c_lo, c_hi = -slope, -(slope + ci_half), -(slope - ci_half)
        alpha = math.exp(intercept)
        print(f"\nRAW 4-point fit (PROVISIONAL): c = {c:.3f}  95% CI = [{c_lo:.3f}, {c_hi:.3f}]")
        print(f"  N_safe ≈ {alpha:.1f} / K_ms^{c:.3f}  — uses raw strict_n_safe incl. the")
        print(f"  K=200ms=30 SAMPLING ARTIFACT (20-run). SUPERSEDED by the k-dense-corrected")
        print(f"  6-point fit (c=0.880); see analyse_kc_formula / Finding E1-7. Do not cite this.")
        return alpha, c
    else:
        print("  Insufficient uncensored N_safe values for regression")
        return None, None



KC_POINTS = [
    (50,  175, "k-sweep 20-run: N=180 p_fail=10%"),
    (100,  95, "cliff-dense 50-run: first p_fail>=10%"),
    (150,  66, "cross-val 10-run: strict N_safe"),
    (200,  55, "k-dense 50-run: N=55 p_fail=12% (corrects k-sweep artifact 30)"),
    (400,  25, "k-sweep 20-run: N=30 p_fail=5%"),
    (500,  25, "k-dense 50-run: N=25 p_fail=22%"),
]


def analyse_kc_formula() -> tuple[float, float]:
    """Authoritative K-exponent fit N_safe = alpha / K_ms^c (Finding E1-7). Returns (alpha, c)."""
    print("\n" + "═" * 60)
    print("KC-FORMULA — authoritative K-exponent fit (Finding E1-7)")
    print("═" * 60)
    K = np.array([p[0] for p in KC_POINTS], float)
    N10 = np.array([p[1] for p in KC_POINTS], float)
    print(f"  {'K_ms':>5}  {'N_10':>5}  basis")
    for k, n, b in KC_POINTS:
        print(f"  {int(k):>5}  {int(n):>5}  {b}")
    slope, intercept, r, _, se = sp.linregress(np.log(K), np.log(N10))
    c, alpha = -slope, math.exp(intercept)
    ci_half = sp.t.ppf(0.975, len(K) - 2) * se
    c_lo, c_hi = -(slope + ci_half), -(slope - ci_half)
    print(f"\n  N_safe ≈ {alpha:.0f} / K_ms^{c:.3f}   (C=1, T_rem≈10s)")
    print(f"  c = {c:.3f}   95% CI = [{c_lo:.3f}, {c_hi:.3f}]   r = {r:.4f}")
    print(f"  c=1.0 {'inside' if c_lo <= 1.0 <= c_hi else 'OUTSIDE'} CI → "
          f"{'sub-linear' if c_hi < 1.0 else 'linear not excluded'}")
    m = K != 150
    s2 = sp.linregress(np.log(K[m]), np.log(N10[m]))
    pred = math.exp(s2.intercept) * 150 ** s2.slope
    print(f"  cross-val (leave K=150 out): predicted {pred:.0f} vs observed 66  "
          f"(err {100 * (pred - 66) / 66:+.0f}%)")
    return alpha, c



K_CROSS_VAL = 150

def analyse_cross_val(df: pd.DataFrame,
                      alpha: float | None = None,
                      c: float | None = None) -> None:
    print("\n" + "═" * 60)
    print(f"CROSS-VAL — unseen K={K_CROSS_VAL}ms (C=1, T_rem=10s)")
    print("═" * 60)
    asp = df[df["framework"] == "aspnet"].sort_values("N")
    rate_table(asp)
    n_s = strict_n_safe(asp)

    if alpha is not None and c is not None:
        predicted = alpha / (K_CROSS_VAL ** c)
        print(f"\nk-sweep formula prediction: N_safe ≈ {predicted:.0f}  "
              f"(α={alpha:.1f}, c={c:.3f}, K={K_CROSS_VAL}ms)")
    else:
        predicted = None
        print("\nNo k-sweep formula available — run k-sweep first for quantitative prediction")

    print(f"Observed strict N_safe = {n_s}")
    if predicted and n_s:
        err = abs(n_s - predicted) / predicted * 100
        verdict = "✓ within 20%" if err <= 20 else "✗ outside 20%"
        print(f"Error = {err:.0f}%  {verdict}")
    if n_s and n_s >= asp["N"].max():
        print("  → Cliff not reached in tested range")



_RUN_RE = re.compile(r"run \d+/\d+: (\d+) req\s+(\d+) cancelled\s+L1=(\d+|n/a)")
_CELL_RE = re.compile(r"=== K=(\d+) N=(\d+) ===")
_SPIKE_FACTOR = 5


def analyse_log_runs(log_dir: Path) -> None:
    import re as _re
    print("\n" + "═" * 60)
    print("LOG ANALYSIS — Per-run bimodal structure (k-sweep logs)")
    print("═" * 60)

    log_files = sorted(log_dir.glob("k-sweep_K*_*.log"))
    if not log_files:
        print(f"  No k-sweep log files found in {log_dir}")
        return

    data: dict[int, dict[int, list]] = {}
    for log_file in log_files:
        cur_K, cur_N = None, None
        with log_file.open() as fh:
            for line in fh:
                cm = _CELL_RE.search(line)
                if cm:
                    cur_K, cur_N = int(cm.group(1)), int(cm.group(2))
                    continue
                if cur_K is None:
                    continue
                rm = _RUN_RE.search(line)
                if rm:
                    n_req = int(rm.group(1))
                    n_can = int(rm.group(2))
                    l1 = int(rm.group(3)) if rm.group(3) != "n/a" else None
                    data.setdefault(cur_K, {}).setdefault(cur_N, []).append((n_req, n_can, l1))

    for K in sorted(data):
        print(f"\nK={K}ms  (spike threshold: L1 > {_SPIKE_FACTOR * K}ms = {_SPIKE_FACTOR}×K)")
        print(f"  {'N':>6}  {'fails':>6}  {'total':>6}  {'p_fail':>7}  "
              f"{'CI_lo':>6}  {'CI_hi':>6}  {'spikes':>7}")
        print("  " + "─" * 55)
        for N in sorted(data[K]):
            runs = data[K][N]
            n_total = len(runs)
            n_fail = sum(1 for r in runs if r[1] == 0)
            n_spike = sum(1 for r in runs if r[2] is not None and r[2] > _SPIKE_FACTOR * K)
            lo, hi = wilson_ci(n_fail, n_total)
            p_fail = n_fail / n_total
            print(f"  {N:>6}  {n_fail:>6}  {n_total:>6}  {p_fail:>7.1%}  "
                  f"{lo:>6.1%}  {hi:>6.1%}  {n_spike:>5} spk")

        Ns = sorted(data[K])
        pfails = [sum(1 for r in data[K][N] if r[1] == 0) / len(data[K][N]) for N in Ns]
        from_zero = [p for p in pfails if p > 0]
        if not from_zero:
            print(f"  → No failures observed at any N — safe zone")
        else:
            first_fail_N = Ns[pfails.index(from_zero[0]) if from_zero else -1]
            print(f"  → First failures at N={first_fail_N}  "
                  f"(per-run failure rates: {[f'{p:.0%}' for p in pfails]})")



def analyse_linear_formula(df: pd.DataFrame) -> None:
    print("\n" + "═" * 60)
    print("LINEAR FORMULA TEST — N_safe × K_ms^c for c ∈ {0.5, 1.0, 1.07}")
    print("═" * 60)
    asp = df[df["framework"] == "aspnet"]

    results = []
    for K, grp in asp.groupby("yield_interval_ms"):
        n_s = strict_n_safe(grp)
        if n_s:
            results.append((int(K), n_s))

    if len(results) < 2:
        print("  Insufficient N_safe values — run k-sweep first")
        return

    print(f"\n{'K_ms':>6}  {'N_safe':>7}  {'N×K':>9}  {'N×√K':>9}  {'N×K^1.07':>10}")
    print("─" * 48)
    prod_linear, prod_sqrt, prod_107 = [], [], []
    for K, N in results:
        p1 = N * K
        p05 = N * math.sqrt(K)
        p107 = N * (K ** 1.07)
        prod_linear.append(p1)
        prod_sqrt.append(p05)
        prod_107.append(p107)
        print(f"{K:>6}  {N:>7}  {p1:>9.0f}  {p05:>9.1f}  {p107:>10.1f}")

    def cv(vals: list) -> float:
        import statistics as st
        return st.stdev(vals) / st.mean(vals) * 100

    print(f"\nCoefficient of variation (lower = more consistent):")
    print(f"  N × K_ms     CV = {cv(prod_linear):.1f}%  (c=1.0)")
    print(f"  N × √K_ms    CV = {cv(prod_sqrt):.1f}%  (c=0.5)")
    print(f"  N × K_ms^1.07 CV = {cv(prod_107):.1f}%  (c=1.07, current formula)")

    best = min([(cv(prod_linear), "c=1.0"), (cv(prod_sqrt), "c=0.5"), (cv(prod_107), "c=1.07")])
    print(f"\nBest fit on RAW strict_n_safe: {best[1]} (CV={best[0]:.1f}%)")
    print("⚠ PROVISIONAL / SUPERSEDED: this test uses raw strict_n_safe including the K=200ms=30")
    print("  20-run sampling artifact, which biases the exponent toward c≈1.0 (linear). The")
    print("  k-dense-corrected 6-point fit gives c=0.880 (sub-linear) — see analyse_kc_formula /")
    print("  Finding E1-7. The authoritative formula is N_safe ≈ 5499 / K_ms^0.880, NOT linear.")



def analyse_cliff_dense(per_run_df: pd.DataFrame) -> None:
    print("\n" + "═" * 60)
    print("CLIFF-DENSE — Per-run failure probability vs N (K=100ms)")
    print("═" * 60)
    asp = per_run_df[per_run_df["framework"] == "aspnet"].copy()
    asp["failed"] = (asp["n_cancelled"] == 0).astype(int)

    print(f"\n{'N':>6}  {'fails':>6}  {'total':>6}  {'p_fail':>7}  {'CI_lo':>6}  {'CI_hi':>6}")
    print("─" * 45)
    rows = []
    for N, grp in asp.groupby("N"):
        n_total = len(grp)
        n_fail = int(grp["failed"].sum())
        lo, hi = wilson_ci(n_fail, n_total)
        p_fail = n_fail / n_total
        rows.append((int(N), n_fail, n_total, p_fail, lo, hi))
        print(f"{int(N):>6}  {n_fail:>6}  {n_total:>6}  {p_fail:>7.1%}  {lo:>6.1%}  {hi:>6.1%}")

    if len(rows) < 3:
        print("  Not enough cells for trend analysis")
        return

    p_vals = [r[3] for r in rows]
    Ns = [r[0] for r in rows]
    monotone = all(p_vals[i] <= p_vals[i + 1] for i in range(len(p_vals) - 1))
    print(f"\nMonotonically increasing p_fail: {'YES' if monotone else 'NO (non-monotonic)'}")

    nonzero = [(N, p) for N, p in zip(Ns, p_vals) if 0 < p < 1]
    if len(nonzero) >= 3:
        try:
            from scipy.optimize import curve_fit
            def logistic(x, x0, k):
                return 1 / (1 + np.exp(-k * (x - x0)))
            (x0, k), _ = curve_fit(logistic, Ns, p_vals, p0=[Ns[len(Ns)//2], 0.05],
                                   maxfev=5000)
            N_10 = x0 - math.log(9) / k
            N_50 = x0
            N_90 = x0 + math.log(9) / k
            print(f"\nLogistic fit:")
            print(f"  N_10 (10% failure) ≈ {N_10:.0f}")
            print(f"  N_50 (50% failure) ≈ {N_50:.0f}")
            print(f"  N_90 (90% failure) ≈ {N_90:.0f}")
            print(f"  Transition width N_90 - N_10 ≈ {N_90 - N_10:.0f}")
            if N_90 - N_10 < 15:
                print("  → Near-deterministic cliff (width < 15 N-units)")
            elif N_90 - N_10 < 40:
                print("  → Moderately stochastic cliff (width 15–40 N-units)")
            else:
                print("  → Clearly stochastic cliff (width > 40 N-units)")
        except Exception:
            print("  (logistic fit did not converge — not enough variance in tested range)")
    else:
        print("  (insufficient variance for logistic fit — extend N range or increase runs)")



def analyse_trem_sweep(data_dir: Path) -> None:
    print("\n" + "═" * 60)
    print("T_REM SWEEP — N_10 ∝ T_remaining? (K=100ms, C=1)")
    print("═" * 60)
    K_MS = 100
    T_REM_FILES = {
        5:  data_dir / "e1a_t_rem_5s_runs.csv",
        10: data_dir / "e1a_cliff_dense_runs.csv",
        20: data_dir / "e1a_t_rem_20s_runs.csv",
    }
    results = []
    for T_rem, path in sorted(T_REM_FILES.items()):
        if not path.exists():
            print(f"\nT_rem={T_rem}s: missing {path.name}")
            continue
        df = pd.read_csv(path)
        asp = df[df["framework"] == "aspnet"].copy()
        n_dropped = int((asp["n_requests"] > asp["N"]).sum())
        if n_dropped:
            print(f"  [W1-6] dropped {n_dropped} bleed-over run(s) with n_requests > N")
        asp = asp[asp["n_requests"] <= asp["N"]].copy()
        asp["failed"] = (asp["n_cancelled"] == 0).astype(int)

        print(f"\nT_rem={T_rem}s  (CPU_DURATION_S={T_rem + 5}):")
        print(f"  {'N':>6}  {'fails':>6}  {'total':>6}  {'p_fail':>7}  {'CI_lo':>6}  {'CI_hi':>6}")
        print("  " + "─" * 43)
        p_rows = []
        for N, grp in asp.groupby("N"):
            n_total = len(grp)
            n_fail = int(grp["failed"].sum())
            lo, hi = wilson_ci(n_fail, n_total)
            p_rows.append((int(N), n_fail, n_total, n_fail / n_total))
            print(f"  {int(N):>6}  {n_fail:>6}  {n_total:>6}  {n_fail/n_total:>7.1%}  {lo:>6.1%}  {hi:>6.1%}")

        N_10 = next((r[0] for r in p_rows if r[3] >= 0.10), None)
        if N_10 is None and p_rows:
            N_10 = p_rows[-1][0]
            print(f"  → p_fail never reached 10% — N_10 right-censored at N={N_10}")
        else:
            print(f"  → N_10 (first p_fail ≥ 10%) = {N_10}")

        if N_10:
            A = N_10 * K_MS / (T_rem * 1000)
            print(f"  → A = N_10 × K_ms / T_rem_ms = {N_10} × {K_MS} / {T_rem*1000} = {A:.4f}")
            results.append((T_rem, N_10, A))

    print("\n" + "─" * 60)
    if len(results) < 2:
        print("Not enough T_rem values measured yet — run both T_REM=5 and T_REM=20")
        return

    import statistics as _st
    A_vals = [r[2] for r in results]
    mean_A = _st.mean(A_vals)
    cv = (_st.stdev(A_vals) / mean_A * 100) if len(A_vals) >= 2 else float("nan")

    print(f"\nSummary (K={K_MS}ms):")
    print(f"  {'T_rem':>6}  {'N_10':>6}  {'A = N_10×K/T':>14}  {'Predicted N_10':>14}")
    for T_rem, N_10, A in results:
        pred = round(mean_A * T_rem * 1000 / K_MS)
        print(f"  {T_rem:>6}s  {N_10:>6}  {A:>14.4f}  {pred:>14}")

    print(f"\n  Mean A = {mean_A:.4f}   CV = {cv:.1f}%")
    if cv < 20:
        alpha = mean_A * 1000
        print(f"\n✓ T_remaining scales linearly (CV={cv:.1f}% < 20%)")
        print(f"  Full formula: N_safe ≈ {alpha:.0f} × T_rem_s / K_ms")
        print(f"              = {mean_A:.3f} × T_rem_ms / K_ms")
    elif cv < 40:
        print(f"\n⚠ Weak linear scaling (CV={cv:.1f}%, 20–40%)")
        print(f"  T_remaining may be in the formula but relationship is noisy")
    else:
        print(f"\n✗ T_remaining does not scale linearly (CV={cv:.1f}% > 40%)")
        print(f"  Formula is K_ms-only; T_rem=10s is a hard fixed condition")




def main() -> None:
    parser = argparse.ArgumentParser(description="E1a analysis")
    parser.add_argument("--only", choices=["causal", "nsweep", "cliff", "k-sweep", "kc-formula", "cross-val",
                                           "log-analysis", "linear-formula", "cliff-dense",
                                           "t-rem-sweep"],
                        help="Run only one section")
    args = parser.parse_args()

    files = {
        "cpu":         DATA / "e1a_cpu.csv",
        "async":       DATA / "e1a_async.csv",
        "nsweep":      DATA / "e1a_nsweep.csv",
        "cliff_scan":  DATA / "e1a_cliff_scan.csv",
        "k_sweep":     DATA / "e1a_cliff_K_sweep.csv",
        "cross_val":   DATA / "e1a_cross_val.csv",
        "cliff_dense": DATA / "e1a_cliff_dense.csv",
        "cliff_dense_runs": DATA / "e1a_cliff_dense_runs.csv",
    }
    log_dir = DATA / "logs"

    print("=" * 60)
    print("E1a — Cliff: Existence, Causality, and Formula")
    print("=" * 60)

    only = args.only

    if only in (None, "causal"):
        if files["cpu"].exists() and files["async"].exists():
            analyse_causal(pd.read_csv(files["cpu"]), pd.read_csv(files["async"]))
        else:
            missing = [k for k in ("cpu", "async") if not files[k].exists()]
            print(f"\nMissing for causal: {missing} — run scripts/sq1/e1a_run.sh causal")

    if only in (None, "nsweep"):
        if files["nsweep"].exists():
            analyse_nsweep(pd.read_csv(files["nsweep"]))
        else:
            print(f"\nMissing: e1a_nsweep.csv — run scripts/sq1/e1a_run.sh nsweep")

    if only in (None, "cliff"):
        if files["cliff_scan"].exists():
            analyse_cliff_scan(pd.read_csv(files["cliff_scan"]))
        else:
            print(f"\nMissing: e1a_cliff_scan.csv — run scripts/sq1/e1a_run.sh cliff-scan")

    alpha, c = None, None
    if only in (None, "k-sweep"):
        if files["k_sweep"].exists():
            analyse_k_sweep(pd.read_csv(files["k_sweep"]))
        else:
            print(f"\nMissing: e1a_cliff_K_sweep.csv — run scripts/sq1/e1a_run.sh k-sweep")

    if only in (None, "k-sweep", "kc-formula"):
        alpha, c = analyse_kc_formula()

    if only in (None, "cross-val"):
        if files["cross_val"].exists():
            if alpha is None:
                alpha, c = analyse_kc_formula()
            analyse_cross_val(pd.read_csv(files["cross_val"]), alpha, c)
        else:
            print(f"\nMissing: e1a_cross_val.csv — run scripts/sq1/e1a_run.sh cross-val")

    if only == "log-analysis":
        analyse_log_runs(log_dir)

    if only == "linear-formula":
        if files["k_sweep"].exists():
            analyse_linear_formula(pd.read_csv(files["k_sweep"]))
        else:
            print(f"\nMissing: e1a_cliff_K_sweep.csv — run scripts/sq1/e1a_run.sh k-sweep")

    if only == "cliff-dense":
        if files["cliff_dense_runs"].exists():
            analyse_cliff_dense(pd.read_csv(files["cliff_dense_runs"]))
        elif files["cliff_dense"].exists():
            print("Per-run CSV not found; showing per-cell summary only:")
            rate_table(pd.read_csv(files["cliff_dense"]))
        else:
            print(f"\nMissing: e1a_cliff_dense_runs.csv — run scripts/sq1/e1a_run.sh cliff-dense")

    if only == "t-rem-sweep":
        analyse_trem_sweep(DATA)


if __name__ == "__main__":
    main()
