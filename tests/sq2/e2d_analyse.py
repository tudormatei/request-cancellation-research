#!/usr/bin/env python3
"""Analyses E2d outbound gRPC cancellation data."""

import csv
import statistics
from pathlib import Path

REPO = Path(__file__).parent.parent.parent
INPUT = REPO / "experiments" / "sq2" / "e2d" / "e2d_grpc.csv"


def load_rows(path: Path) -> list[dict]:
    if not path.exists():
        print(f"No data at {path}")
        return []
    with path.open() as f:
        return list(csv.DictReader(f))


def summarise(rows: list[dict]) -> None:
    by_fw: dict[str, list[dict]] = {}
    for r in rows:
        by_fw.setdefault(r["framework"], []).append(r)

    print("\n── E2d — In-band abort (gRPC / HTTP2 RST_STREAM) ──────────────────────")
    print(f"{'Framework':<12} {'runs':>5} {'det%':>7} {'grpc_cancel%':>13} "
          f"{'ds_confirmed%':>14} {'ds_lat_ms (mean)':>18}")
    print("─" * 75)

    for fw, fw_rows in sorted(by_fw.items()):
        n = len(fw_rows)

        det_rates = [float(r["detection_rate"])           for r in fw_rows]
        grpc_rates = [float(r["outbound_grpc_cancelled"])  for r in fw_rows]
        ds_confirmed = [int(r["downstream_grpc_confirmed"])  for r in fw_rows]
        ds_lats = [float(r["downstream_grpc_confirm_latency_ms"])
                        for r in fw_rows if r["downstream_grpc_confirm_latency_ms"] not in ("", "None")]

        det_pct = round(statistics.mean(det_rates)  * 100, 1)
        grpc_pct = round(statistics.mean(grpc_rates) * 100, 1)
        ds_pct = round(sum(ds_confirmed) / n * 100, 1)
        ds_lat = round(statistics.mean(ds_lats), 1) if ds_lats else None

        print(f"{fw:<12} {n:>5} {det_pct:>6.1f}% {grpc_pct:>12.1f}% "
              f"{ds_pct:>13.1f}% {str(ds_lat)+' ms':>18}")

    print()
    print("Expected (both frameworks): det=100%, grpc_cancel=100%, ds_confirmed=100%")
    print()
    print("Interpretation:")
    print("  If both frameworks show 100% across all three metrics:")
    print("  → In-band abort (RST_STREAM) is handled correctly by both architectures.")
    print("  → The reactive model's failure is confirmed specific to OUT-OF-BAND abort")
    print("    protocols (PostgreSQL CancelRequest) — not to all IO cancellation.")
    print()
    print("  RST_STREAM carries the HTTP/2 stream ID — no pipelining ambiguity,")
    print("  no separate TCP connection, no wait for server confirmation required.")
    print("  The two structural conflicts that prevent a PostgreSQL bridge do not exist.")


def main() -> None:
    rows = load_rows(INPUT)
    if rows:
        summarise(rows)


if __name__ == "__main__":
    main()
