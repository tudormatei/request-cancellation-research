#!/bin/bash

set -e
REPO="$(cd "$(dirname "$0")/../.." && pwd)"

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate thesis-stats

MODE=${1:-help}

if [[ "$MODE" == "help" ]]; then
  echo "Usage: bash scripts/sq3/e3_run.sh <e3a|e3c|e3c-baseline|e3c-y-sweep>"
  exit 0
fi

LOGDIR="$REPO/experiments/sq3/logs"
mkdir -p "$LOGDIR"
LOGFILE="$LOGDIR/${MODE}_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee "$LOGFILE") 2>&1
echo "Logging to: $LOGFILE"
echo "Started at: $(date)"
echo ""

E3_THREAD_POOL=200
E3_YIELD_MS=100

restart_aspnet_e3() {
  THREAD_POOL_MAX=$E3_THREAD_POOL YIELD_INTERVAL_MS=$E3_YIELD_MS \
    docker compose -f "$REPO/docker-compose.yml" --profile aspnet up -d --build --force-recreate \
    > /dev/null 2>&1
  sleep 15
  docker logs thesis_aspnet 2>&1 | grep -E "max_worker|aspnet ready|yield"
}

restart_webflux_e3() {
  YIELD_INTERVAL_MS=$E3_YIELD_MS \
    docker compose -f "$REPO/docker-compose.yml" --profile spring-webflux up -d --build --force-recreate \
    > /dev/null 2>&1
  sleep 20
}

collect_e3() { python "$REPO/tests/sq3/e3_collect.py" "$@"; }

if [[ "$MODE" == "e3a" ]]; then
  echo "▶ E3a — cross-check (wave2_delay ≈ ghost_holdtime)"
  echo "  Both frameworks run concurrently (different ports: 8081/8083)"

  restart_aspnet_e3
  restart_webflux_e3
  collect_e3 --mode e3a --runs 1

  echo ""
  echo "E3a complete. Analyse:"
  echo "  conda activate thesis-stats && python $REPO/tests/sq3/e3_analyse.py --only e3a"
fi

if [[ "$MODE" == "e3c" ]]; then
  echo "▶ E3c — cascade dynamics (sustained load, pool exhaustion)"
  echo "  X∈{25,50,125} req/s | Y=10% cancel | 5 min per cell"
  echo ""

  echo "── ASP.NET ──"
  restart_aspnet_e3
  for X in 25 50 125; do
    echo "=== aspnet X=${X}rps ===" && collect_e3 --mode e3c --framework aspnet --X $X --Y 0.10 --duration 300
    sleep 30
  done

  echo ""
  echo "── WebFlux ──"
  restart_webflux_e3
  for X in 25 50 125; do
    echo "=== webflux X=${X}rps ===" && collect_e3 --mode e3c --framework webflux --X $X --Y 0.10 --duration 300
    sleep 30
  done

  echo ""
  echo "E3c complete. Analyse:"
  echo "  conda activate thesis-stats && python $REPO/tests/sq3/e3_analyse.py --only e3c"
fi

if [[ "$MODE" == "e3c-baseline" ]]; then
  echo "▶ E3c baseline — Y=0% (no cancellations), WebFlux, X∈{25,50,125}"
  echo "  Purpose: isolate ghost connection contribution from baseline pool pressure."
  echo "  If Y=0% shows pool_exhausted≈0 at all X, collapse at Y=10% is ghost-driven."
  echo ""

  restart_webflux_e3
  for X in 25 50 125; do
    echo "=== webflux X=${X}rps Y=0% ===" && collect_e3 --mode e3c --framework webflux --X $X --Y 0.0 --duration 300
    sleep 30
  done

  echo ""
  echo "E3c baseline complete. Analyse:"
  echo "  conda activate thesis-stats && python $REPO/tests/sq3/e3_analyse.py --only e3c"
fi

if [[ "$MODE" == "e3c-y-sweep" ]]; then
  echo "▶ E3c Y-sweep — R_max formula cross-validation (WebFlux, X=25 rps)"
  echo "  Y=5%:  R_max≈50 rps → X=25 below threshold → expect stable"
  echo "  Y=20%: R_max≈12 rps → X=25 above threshold → expect collapse"
  echo ""

  restart_webflux_e3
  for Y in 0.05 0.20; do
    echo "=== webflux X=25rps Y=${Y} ===" && collect_e3 --mode e3c --framework webflux --X 25 --Y $Y --duration 300
    sleep 30
  done

  echo ""
  echo "E3c Y-sweep complete. Analyse:"
  echo "  conda activate thesis-stats && python $REPO/tests/sq3/e3_analyse.py --only e3c"
fi

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "E3 ${MODE} finished. Full synthesis:"
echo "  conda activate thesis-stats && python $REPO/tests/sq3/e3_analyse.py"
