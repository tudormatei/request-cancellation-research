#!/bin/bash

set -uo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"

LOGDIR="$REPO/experiments/sq1/logs"
mkdir -p "$LOGDIR"
SUP_LOG="$LOGDIR/enhance_supervise_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee "$SUP_LOG") 2>&1

echo "Supervisor started $(date)"
echo "  per-cell gating handled inside e1a_run.sh (GATE_THRESHOLD=${GATE_THRESHOLD:-0.4})"

docker compose -f "$REPO/docker-compose.yml" up -d postgres >/dev/null 2>&1
for i in $(seq 1 30); do
  [ "$(docker inspect -f '{{.State.Health.Status}}' thesis_postgres 2>/dev/null)" = "healthy" ] && break
  sleep 2
done

run_exp() {
  local mode=$1
  echo ""
  echo "════════════════════════════════════════════════════════════════════"
  echo "QUEUE: $mode  ($(date))"
  echo "════════════════════════════════════════════════════════════════════"
  bash "$REPO/scripts/sq1/e1a_run.sh" "$mode"
  local rc=$?
  echo "── $mode finished rc=$rc ($(date)) ──"
  docker compose -f "$REPO/docker-compose.yml" --profile aspnet --profile spring-webflux --profile go down >/dev/null 2>&1
  docker compose -f "$REPO/docker-compose.yml" up -d postgres >/dev/null 2>&1
  return $rc
}

for mode in webflux-sched noinject go-cliff; do
  run_exp "$mode"; rc=$?
  [ "$rc" -ne 0 ] && echo "NOTE: $mode exited rc=$rc — continuing to next experiment."
done

echo ""
echo "Supervisor done $(date). Log: $SUP_LOG"
echo "Analyse:  conda activate thesis-stats && python tests/sq1/e1_enhance_analyse.py"
echo "Figure:   python tests/sq1/e1_master.py"
