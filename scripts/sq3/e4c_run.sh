#!/usr/bin/env bash
set -uo pipefail
REPO="/home/tudor/dev/request-cancellation-research"
LOG="$REPO/experiments/sq3/logs/e4c_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee "$LOG") 2>&1
echo "START $(date)"
for fw in aspnet webflux mvc; do
  echo "==== $fw ===="
  conda run -n thesis-stats python "$REPO/tests/sq3/e4_collect.py" --mode e4c --framework "$fw" --runs 20
done
echo "DONE $(date)"
