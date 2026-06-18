#!/bin/bash

set -e
REPO="$(cd "$(dirname "$0")/../.." && pwd)"

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate thesis-stats

MODE=${1:-help}

if [[ "$MODE" == "help" ]]; then
  echo "Usage: bash scripts/sq3/e4_run.sh <e4a|e4b|e4b-transition|e4b-exceptions>"
  echo "       DSTAR=<ms> required for e4b-transition and e4b-exceptions"
  exit 0
fi

LOGDIR="$REPO/experiments/sq3/logs"
mkdir -p "$LOGDIR"
LOGFILE="$LOGDIR/${MODE}_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee "$LOGFILE") 2>&1
echo "Logging to: $LOGFILE"
echo "Started at: $(date)"
echo ""

E4_THREAD_POOL=200
E4_YIELD_MS=100

restart_aspnet_e4() {
  THREAD_POOL_MAX=$E4_THREAD_POOL YIELD_INTERVAL_MS=$E4_YIELD_MS \
    docker compose -f "$REPO/docker-compose.yml" --profile aspnet up -d --build --force-recreate \
    > /dev/null 2>&1
  sleep 15
  docker logs thesis_aspnet 2>&1 | grep -E "max_worker|aspnet ready|yield"
}

restart_webflux_e4() {
  YIELD_INTERVAL_MS=$E4_YIELD_MS \
    docker compose -f "$REPO/docker-compose.yml" --profile spring-webflux up -d --build --force-recreate \
    > /dev/null 2>&1
  sleep 20
}

restart_mvc_e4() {
  docker compose -f "$REPO/docker-compose.yml" --profile spring-mvc up -d --build --force-recreate \
    > /dev/null 2>&1
  sleep 15
}

collect_e4() { python "$REPO/tests/sq3/e4_collect.py" "$@"; }

if [[ "$MODE" == "e4a" ]]; then
  echo "▶ E4a — log audit anchor (ghost write visibility)"

  echo "── ASP.NET ──"
  restart_aspnet_e4
  collect_e4 --mode e4a --framework aspnet --runs 20

  echo "── WebFlux ──"
  restart_webflux_e4
  collect_e4 --mode e4a --framework webflux --runs 20

  echo "── Spring MVC ──"
  restart_mvc_e4
  collect_e4 --mode e4a --framework mvc --runs 20

  echo ""
  echo "E4a complete. Analyse:"
  echo "  conda activate thesis-stats && python $REPO/tests/sq3/e4_analyse.py --only e4a"
fi

if [[ "$MODE" == "e4b" ]]; then
  echo "▶ E4b — D* sweep (INSERT duration vs ghost write rate)"

  echo "── ASP.NET (10 D values × 20 trials) ──"
  restart_aspnet_e4
  for D in 50 75 100 125 150 175 200 250 500 1000; do
    echo "=== aspnet D=${D}ms ===" && collect_e4 --mode e4b --framework aspnet --D $D --runs 20
  done

  echo "── WebFlux (3 confirmatory D values × 10 trials) ──"
  restart_webflux_e4
  for D in 100 250 1000; do
    echo "=== webflux D=${D}ms ===" && collect_e4 --mode e4b --framework webflux --D $D --runs 10
  done

  echo ""
  echo "E4b complete. Identify D* from analysis, then set DSTAR and run e4b-transition."
  echo "  conda activate thesis-stats && python $REPO/tests/sq3/e4_analyse.py --only e4b"
fi

if [[ "$MODE" == "e4b-transition" ]]; then
  if [[ -z "$DSTAR" ]]; then
    echo "✗ DSTAR env var required. Run e4b first, read D* from analysis, then:"
    echo "  DSTAR=<ms> bash scripts/sq3/e4_run.sh e4b-transition"
    exit 1
  fi

  echo "▶ E4b-transition — logistic transition width (DSTAR=${DSTAR}ms)"
  echo "  D values: $((DSTAR-50)) $((DSTAR-25)) $DSTAR $((DSTAR+25)) $((DSTAR+50))"

  restart_aspnet_e4
  for D in $((DSTAR-50)) $((DSTAR-25)) $DSTAR $((DSTAR+25)) $((DSTAR+50)); do
    echo "=== aspnet transition D=${D}ms ===" && collect_e4 --mode e4b-transition --D $D --runs 50
  done

  echo ""
  echo "E4b-transition complete. Analyse:"
  echo "  conda activate thesis-stats && python $REPO/tests/sq3/e4_analyse.py --only e4b-transition --D-star $DSTAR"
fi

if [[ "$MODE" == "e4b-exceptions" ]]; then
  if [[ -z "$DSTAR" ]]; then
    echo "✗ DSTAR env var required."
    echo "  DSTAR=<ms> bash scripts/sq3/e4_run.sh e4b-exceptions"
    exit 1
  fi

  echo "▶ E4b-exceptions — Npgsql exception distinguishability (DSTAR=${DSTAR}ms)"
  echo "  D*-50ms (ghost write expected) and D*+50ms (clean cancel expected)"

  restart_aspnet_e4
  collect_e4 --mode e4b-exceptions --D-star $DSTAR --runs 30

  echo ""
  echo "E4b-exceptions complete. Analyse:"
  echo "  conda activate thesis-stats && python $REPO/tests/sq3/e4_analyse.py --only e4b-exceptions"
fi

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "E4 ${MODE} finished. Full synthesis:"
echo "  conda activate thesis-stats && python $REPO/tests/sq3/e4_analyse.py"
