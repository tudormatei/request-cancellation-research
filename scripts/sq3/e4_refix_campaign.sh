#!/usr/bin/env bash

set -uo pipefail
REPO="/home/tudor/dev/request-cancellation-research"
COL="$REPO/tests/sq3/e4_collect.py"
PY="conda run -n thesis-stats python"
LOG="$REPO/experiments/sq3/logs/e4_refix_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee "$LOG") 2>&1
echo "START $(date)  log=$LOG"

echo "=== RUN A: cancel_at=50ms dense ==="
for D in $(shuf -e 35 48 50 52 54 56 58 60 62 110); do
  $PY "$COL" --mode e4b-transition --D "$D" --runs 50
done

echo "=== RUN B: cancel_at=200ms validation ==="
for D in $(shuf -e 150 185 198 200 202 204 206 208 210 215 280); do
  $PY "$COL" --mode e4b-transition --D "$D" --runs 30 --cancel-at 0.2
done

echo "=== RUN C: WebFlux E4b re-run ==="
$PY "$COL" --mode e4b --framework webflux --runs 20

echo "DONE $(date)"
