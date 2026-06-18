#!/bin/bash

set -uo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"

LOGDIR="$REPO/experiments/sq1/logs"
mkdir -p "$LOGDIR"
SUP_LOG="$LOGDIR/resume_supervise_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee "$SUP_LOG") 2>&1

echo "Resume supervisor started $(date)"
echo "  per-cell gating inside e1a_run.sh (GATE_THRESHOLD=${GATE_THRESHOLD:-0.4})"

docker compose -f "$REPO/docker-compose.yml" up -d postgres >/dev/null 2>&1
for i in $(seq 1 30); do
  [ "$(docker inspect -f '{{.State.Health.Status}}' thesis_postgres 2>/dev/null)" = "healthy" ] && break
  sleep 2
done

run() {
  echo ""
  echo "════════════════════════════════════════════════════════════════════"
  echo "QUEUE: $*  ($(date))"
  echo "════════════════════════════════════════════════════════════════════"
  bash "$REPO/scripts/sq1/e1a_run.sh" "$@"; local rc=$?
  echo "── ($*) finished rc=$rc ($(date)) ──"
  docker compose -f "$REPO/docker-compose.yml" --profile aspnet --profile spring-webflux --profile go down >/dev/null 2>&1
  docker compose -f "$REPO/docker-compose.yml" up -d postgres >/dev/null 2>&1
  return $rc
}

run go-cliff; echo "NOTE: go-cliff rc=$?"
run noinject --only-K 200; echo "NOTE: noinject K200 rc=$?"
run noinject --only-K 400; echo "NOTE: noinject K400 rc=$?"

echo ""
echo "Resume supervisor done $(date). Log: $SUP_LOG"
echo "Analyse:  conda activate thesis-stats && python tests/sq1/e1_enhance_analyse.py"
echo "Figure:   python tests/sq1/e1_master.py"
