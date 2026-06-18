#!/bin/bash

set -e
REPO="$(cd "$(dirname "$0")/../.." && pwd)"

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate thesis-stats

MODE=${1:-help}

if [[ "$MODE" == "help" ]]; then
  echo "Usage: bash scripts/sq2/e2_run.sh <e2c|e2a|e2b>"
  exit 0
fi

LOGDIR="$REPO/experiments/sq2/logs"
mkdir -p "$LOGDIR"
LOGFILE="$LOGDIR/${MODE}_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee "$LOGFILE") 2>&1
echo "Logging to: $LOGFILE"
echo "Started at: $(date)"

E2_THREAD_POOL=200
E2_YIELD_MS=100

restart_aspnet_e2() {
  THREAD_POOL_MAX=$E2_THREAD_POOL YIELD_INTERVAL_MS=$E2_YIELD_MS \
    docker compose -f "$REPO/docker-compose.yml" --profile aspnet up -d --force-recreate \
    > /dev/null 2>&1
  sleep 15
  docker logs thesis_aspnet 2>&1 | grep -E "max_worker|aspnet ready"
}

restart_webflux_e2() {
  YIELD_INTERVAL_MS=$E2_YIELD_MS \
    docker compose -f "$REPO/docker-compose.yml" --profile spring-webflux up -d --force-recreate \
    > /dev/null 2>&1
  sleep 15
}

restart_mvc_e2() {
  docker compose -f "$REPO/docker-compose.yml" --profile spring-mvc up -d --force-recreate \
    > /dev/null 2>&1
  sleep 20
}

start_downstream() {
  docker compose -f "$REPO/docker-compose.yml" --profile downstream up -d --force-recreate \
    > /dev/null 2>&1
  echo "Waiting for downstream mock (pip install grpcio + proto compile + startup)..."
  sleep 60
  docker logs thesis_downstream 2>&1 | tail -5
}

collect_e2a() { python "$REPO/tests/sq2/e2a_collect.py" "$@"; }
collect_e2b() { python "$REPO/tests/sq2/e2b_collect.py" "$@"; }
collect_e2c() { python "$REPO/tests/sq2/e2c_collect.py" "$@"; }
collect_e2d() { python "$REPO/tests/sq2/e2d_collect.py" "$@"; }
collect_e2layer() { python "$REPO/tests/sq2/e2_layer_collect.py" "$@"; }
collect_e2b_clientwrite() { python "$REPO/tests/sq2/e2b_clientwrite_collect.py" "$@"; }

if [[ "$MODE" == "e2c" ]]; then
  echo "▶ E2c — outbound HTTP cancellation (connection-close protocol)"
  echo "  Downstream mock must be running."
  start_downstream

  echo "── ASP.NET ──"
  restart_aspnet_e2
  collect_e2c --framework aspnet --N 1 --runs 10

  echo "── WebFlux ──"
  restart_webflux_e2
  collect_e2c --framework webflux --N 1 --runs 10

  echo ""
  echo "E2c complete. Analyse:"
  echo "  conda activate thesis-stats && python $REPO/tests/sq2/e2_analyse.py --only e2c"
fi

if [[ "$MODE" == "e2a" ]]; then
  echo "▶ E2a — single-result DB query (full bridge vs no bridge)"

  echo "── ASP.NET (N-sweep) ──"
  restart_aspnet_e2
  for N in 1 5 10 25 50 100 200; do
    echo "=== aspnet N=${N} ===" && collect_e2a --framework aspnet --N $N --runs 10
  done

  echo "── WebFlux (N-sweep) ──"
  restart_webflux_e2
  for N in 1 5 10 25 50 100 200; do
    echo "=== webflux N=${N} ===" && collect_e2a --framework webflux --N $N --runs 10
  done

  echo "── Spring MVC (N=1 qualitative) ──"
  restart_mvc_e2
  collect_e2a --framework mvc --N 1 --runs 5

  echo ""
  echo "E2a complete. Analyse:"
  echo "  conda activate thesis-stats && python $REPO/tests/sq2/e2_analyse.py --only e2a"
fi

if [[ "$MODE" == "e2b" ]]; then
  echo "▶ E2b — streaming DB query (consumption bridge)"

  echo "── ASP.NET ──"
  restart_aspnet_e2
  for N in 1 5 10; do
    echo "=== aspnet stream N=${N} ===" && collect_e2b --framework aspnet --N $N --runs 10
  done

  echo "── WebFlux ──"
  restart_webflux_e2
  for N in 1 5 10; do
    echo "=== webflux stream N=${N} ===" && collect_e2b --framework webflux --N $N --runs 10
  done

  echo ""
  echo "E2b complete. Analyse:"
  echo "  conda activate thesis-stats && python $REPO/tests/sq2/e2_analyse.py --only e2b"
fi

if [[ "$MODE" == "e2d" ]]; then
  echo "▶ E2d — outbound gRPC cancellation (in-band abort / HTTP2 RST_STREAM)"
  echo "  Third cell of IO protocol taxonomy: connection-close | in-band | out-of-band"
  echo "  Downstream mock must support gRPC (port 50051)."
  start_downstream

  echo "── ASP.NET ──"
  restart_aspnet_e2
  collect_e2d --framework aspnet --N 1 --runs 10

  echo "── WebFlux ──"
  restart_webflux_e2
  collect_e2d --framework webflux --N 1 --runs 10

  echo ""
  echo "E2d complete. Analyse:"
  echo "  conda activate thesis-stats && python $REPO/tests/sq2/e2d_analyse.py"
fi

if [[ "$MODE" == "e2-layer" ]]; then
  echo "▶ E2-layer — multi-layer handler timing vs DB gone (verifiability asymmetry)"
  echo "  Measures gap_ms = handler_fired_at - db_gone for each application layer."
  echo "  Negative gap → notification (WebFlux). Positive gap → completion event (ASP.NET)."

  echo "── ASP.NET ──"
  restart_aspnet_e2
  collect_e2layer --framework aspnet --runs 10

  echo "── WebFlux ──"
  restart_webflux_e2
  collect_e2layer --framework webflux --runs 10

  echo ""
  echo "E2-layer complete. Analyse:"
  echo "  conda activate thesis-stats && python $REPO/tests/sq2/e2_layer_analyse.py"
fi

if [[ "$MODE" == "e2b-clientwrite" ]]; then
  echo "▶ E2b-clientwrite — ClientWrite accumulation quantification"
  echo "  WebFlux only. N consecutive streaming cancellations, 120s post-monitor."
  echo "  Each rep restarts the WebFlux container for fresh pool state."

  echo "── N=3 ──"
  collect_e2b_clientwrite --N 3 --reps 5

  echo "── N=5 ──"
  collect_e2b_clientwrite --N 5 --reps 5

  echo "── N=10 ──"
  collect_e2b_clientwrite --N 10 --reps 5

  echo ""
  echo "E2b-clientwrite complete. Analyse:"
  echo "  conda activate thesis-stats && python $REPO/tests/sq2/e2b_clientwrite_analyse.py"
fi

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "E2 ${MODE} finished. Full synthesis:"
echo "  conda activate thesis-stats && python $REPO/tests/sq2/e2_analyse.py"
