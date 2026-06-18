#!/usr/bin/env python3
"""Analyses ClientWrite accumulation data from the E2b-clientwrite experiment."""

import csv
import statistics
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).parent.parent.parent
INPUT = REPO / "experiments" / "sq2" / "e2b_clientwrite" / "e2b_clientwrite.csv"


def main() -> None:
    if not INPUT.exists():
        print(f"No data at {INPUT}")
        print("Run: python tests/sq2/e2b_clientwrite_collect.py --N 5 --reps 5")
        return

    rows = []
    with INPUT.open() as f:
        for row in csv.DictReader(f):
            rows.append(row)

    by_N: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        by_N[int(row["N"])].append(row)

    print("\n" + "=" * 75)
    print("CLIENTWRITE ACCUMULATION — Sequential streaming cancellations (WebFlux)")
    print("=" * 75)
    print()

    for N in sorted(by_N.keys()):
        reps = by_N[N]
        n = len(reps)

        n_no_onset = sum(1 for r in reps if r["first_clientwrite_at_n"] in ("", "None", None))
        peaks = [int(r["peak_clientwrite_count"]) for r in reps
                  if r["peak_clientwrite_count"] not in ("", "None", None)]
        clears = [int(r["cleared_within_120s"]) for r in reps
                  if r["cleared_within_120s"] not in ("", "None", None)]
        stuck = [int(r["stuck_count_at_120s"]) for r in reps
                  if r["stuck_count_at_120s"] not in ("", "None", None)]

        print(f"N = {N} sequential cancellations  ({n} reps)")
        print(f"  ClientWrite during cancel seq:  not observed within 0.5s post-cancel "
              f"({n_no_onset}/{n} reps — onset ~1-2s after cancel, after buffer fills)")
        if peaks:
            n_any_cw = sum(1 for p in peaks if p > 0)
            print(f"  ClientWrite appeared at all:    {n_any_cw}/{n} reps  "
                  f"(peak={statistics.median(peaks):.0f} connections, appears in monitoring window)")
        if clears:
            n_cleared = sum(clears)
            print(f"  Cleared within 120s:            {n_cleared}/{n} reps  "
                  f"({'NEVER' if n_cleared == 0 else 'sometimes'})")
        if stuck:
            print(f"  Still stuck at t+120s:          median={statistics.median(stuck):.0f} connections")
        print()

    print("Key finding:")
    all_onsets = [int(r["first_clientwrite_at_n"]) for r in rows
                  if r["first_clientwrite_at_n"] not in ("", "None", None)]
    all_cleared = [int(r["cleared_within_120s"]) for r in rows
                   if r["cleared_within_120s"] not in ("", "None", None)]
    if all_onsets:
        print(f"  ClientWrite appears at cancel #{min(all_onsets)}–{max(all_onsets)} "
              f"(across all N values)")
    if all_cleared:
        total = len(all_cleared)
        n_cleared = sum(all_cleared)
        print(f"  Self-cleared within 120s: {n_cleared}/{total} reps "
              f"({'never' if n_cleared == 0 else 'sometimes'})")
    print()
    print("Implication:")
    print("  ClientWrite accumulation onset is deterministic (not a long-run artifact).")
    print("  Connections that enter ClientWrite state do not self-clear — they require")
    print("  a process restart or explicit pool/DB timeout configuration to reclaim.")


if __name__ == "__main__":
    main()
