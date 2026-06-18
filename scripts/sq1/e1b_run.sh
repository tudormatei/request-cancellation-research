#!/bin/bash

set -e
REPO="$(cd "$(dirname "$0")/../.." && pwd)"

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate thesis-stats

LOGDIR="$REPO/experiments/sq1/e1b/logs"
mkdir -p "$LOGDIR"
LOGFILE="$LOGDIR/e1b_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee "$LOGFILE") 2>&1
echo "Logging to: $LOGFILE"
echo "Started at: $(date)"
echo ""

RUNS=10

restart_aspnet() {
  local K=$1 T=$2
  THREAD_POOL_MAX=$T YIELD_INTERVAL_MS=$K CPU_DURATION_S=15 \
    docker compose -f "$REPO/docker-compose.yml" --profile aspnet up -d --force-recreate \
    > /dev/null 2>&1
  sleep 15
  docker logs thesis_aspnet 2>&1 | grep -E "yield_interval_ms|max_worker|cpu_duration_s"
}

restart_webflux() {
  local K=$1
  YIELD_INTERVAL_MS=$K \
    docker compose -f "$REPO/docker-compose.yml" --profile spring-webflux up -d --force-recreate \
    > /dev/null 2>&1
  sleep 15
}

echo ""
echo "▶ E1b latency-sweep (K parametric, N=1, T_max=1)"
echo "  Critical control: T_max=1 prevents hill-climbing fast-path"

for K in 10 50 100 200 500; do
  echo ""
  echo "=== K=${K}ms  N=1  T_max=1 ==="
  restart_aspnet $K 1
  restart_webflux $K
  python "$REPO/tests/sq1/e1b_collect.py" \
    --mode latency-sweep --K $K --T 1 --N 1 --runs $RUNS \
    --frameworks aspnet webflux
done

echo ""
echo "▶ E1b tmax-sweep (K=100ms, N=8, T_max varied)"

for T in 1 2 4 8 16; do
  echo ""
  echo "=== K=100ms  N=8  T_max=${T} ==="
  restart_aspnet 100 $T
  python "$REPO/tests/sq1/e1b_collect.py" \
    --mode tmax-sweep --K 100 --T $T --N 8 --runs $RUNS \
    --frameworks aspnet
done

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "E1b complete. Analyse:"
echo "  conda activate thesis-stats"
echo "  python $REPO/tests/sq1/e1b_analyse.py"
