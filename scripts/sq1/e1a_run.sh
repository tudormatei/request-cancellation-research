#!/bin/bash

set -e
REPO="$(cd "$(dirname "$0")/../.." && pwd)"

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate thesis-stats

MODE=${1:-help}
ONLY_K=""
if [[ "$2" == "--only-K" ]]; then ONLY_K="$3"; fi

if [[ "$MODE" == "help" ]]; then
  echo "Usage: bash e1a_run.sh <causal|nsweep|cliff-scan|k-sweep|cross-val> [--only-K <50|100|200|400>]"
  exit 0
fi

LOGDIR="$REPO/experiments/sq1/e1a/logs"
mkdir -p "$LOGDIR"
LOGFILE="$LOGDIR/${MODE}${ONLY_K:+_K${ONLY_K}}_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee "$LOGFILE") 2>&1
echo "Logging to: $LOGFILE"
echo "Started at: $(date)"
echo ""

restart_aspnet() {
  local K=$1 T=$2 CPU_S=${3:-15} CPUS=${4:-1} CPUSET=${5:-0}
  THREAD_POOL_MAX=$T YIELD_INTERVAL_MS=$K CPU_DURATION_S=$CPU_S \
    ASPNET_CPUS=$CPUS ASPNET_CPUSET=$CPUSET \
    docker compose -f "$REPO/docker-compose.yml" --profile aspnet up -d --force-recreate \
    > /dev/null 2>&1
  sleep 15
  docker logs thesis_aspnet 2>&1 | grep -E "yield_interval_ms|max_worker|cpu_duration_s|logical_cpus"
}

restart_webflux() {
  local K=$1 SCHED=${2:-boundedElastic} CPUS=${3:-1.0} CPUSET=${4:-3}
  YIELD_INTERVAL_MS=$K REACTOR_SCHEDULER=$SCHED \
    SPRING_WEBFLUX_CPUS=$CPUS SPRING_WEBFLUX_CPUSET=$CPUSET \
    docker compose -f "$REPO/docker-compose.yml" --profile spring-webflux up -d --force-recreate \
    > /dev/null 2>&1
  sleep 15
  docker logs thesis_spring_webflux 2>&1 | grep -E "reactor_scheduler|yield_interval_ms" | tail -1
}

restart_aspnet_noinject() {
  local K=$1 T=$2 CPU_S=${3:-15} CPUS=${4:-1} CPUSET=${5:-0}
  THREAD_POOL_MAX=$T THREAD_POOL_MIN=$T YIELD_INTERVAL_MS=$K CPU_DURATION_S=$CPU_S \
    ASPNET_CPUS=$CPUS ASPNET_CPUSET=$CPUSET \
    docker compose -f "$REPO/docker-compose.yml" --profile aspnet up -d --force-recreate \
    > /dev/null 2>&1
  sleep 15
  docker logs thesis_aspnet 2>&1 | grep -E "min_worker|max_worker|yield_interval_ms"
}

restart_go() {
  local K=$1 CPU_S=${2:-15} CPUS=${3:-1.0} CPUSET=${4:-0} GMP=${5:-}
  YIELD_INTERVAL_MS=$K CPU_DURATION_S=$CPU_S \
    GO_CPUS=$CPUS GO_CPUSET=$CPUSET GOMAXPROCS=$GMP \
    docker compose -f "$REPO/docker-compose.yml" --profile go up -d --force-recreate \
    > /dev/null 2>&1
  sleep 8
  docker logs thesis_go_service 2>&1 | grep -E "go-service ready"
}

collect() {
  python "$REPO/tests/sq1/e1a_collect.py" "$@"
}

preflight() {
  echo "Pre-flight: $(uptime | grep -oP 'load average: \K[0-9., ]+')"
  local load
  load=$(uptime | grep -oP 'load average: \K[0-9.]+' | head -1)
  if (( $(echo "$load > 0.5" | bc -l) )); then
    echo "✗ load $load > 0.5 — wait before starting"; exit 1
  fi
  echo "✓ load OK"
}

GATE_THRESHOLD=${GATE_THRESHOLD:-0.4}
GATE_CAP_S=${GATE_CAP_S:-5400}
wait_quiet() {
  local waited=0 l l2
  while :; do
    l=$(awk '{print $1}' /proc/loadavg)
    if awk "BEGIN{exit !($l < $GATE_THRESHOLD)}"; then
      sleep 4; l2=$(awk '{print $1}' /proc/loadavg)
      if awk "BEGIN{exit !($l2 < $GATE_THRESHOLD)}"; then
        echo "  [gate] quiet (load=$l2) — running cell"; return 0
      fi
    fi
    if (( waited >= GATE_CAP_S )); then
      echo "  [gate] GAVE UP after $((GATE_CAP_S/60))min (load=$l) — aborting mode"; exit 3
    fi
    (( waited % 300 == 0 )) && echo "  [gate] waiting for quiet… load=$l (${waited}s)"
    sleep 30; waited=$((waited + 30))
  done
}

if [[ "$MODE" == "causal" ]]; then
  K=100
  echo "▶ E1a causal — cpu scenario (K=${K}ms, T_max=N)"
  for N in 1 5 10 25 50 75 100 125 150 200 300; do
    echo "=== cpu N=${N} ===" && restart_aspnet $K $N && restart_webflux $K
    collect --mode causal-cpu --N $N --K $K --T $N --runs 10
  done

  echo ""
  echo "▶ E1a causal — async scenario (causal control, T_max=1)"
  for N in 1 5 10 25 50 100 200 500 750; do
    echo "=== async N=${N} ===" && restart_aspnet $K 1 && restart_webflux $K
    collect --mode causal-async --N $N --K $K --T 1 --runs 10
  done
fi

if [[ "$MODE" == "nsweep" ]]; then
  echo "▶ E1a nsweep (K=100ms, T_max=N)"
  for N in 1 5 10 20 30 40 50 75 100 125 150 175 200; do
    echo "=== N=${N} ===" && restart_aspnet 100 $N
    collect --mode nsweep --N $N --K 100 --T $N --runs 10
  done
fi

if [[ "$MODE" == "cliff-scan" ]]; then
  echo "▶ E1a cliff-scan (K∈{50,100,200}ms)"
  for K in 200 100 50; do
    echo "── K=${K}ms ──"
    case $K in
      200) NS=(35 50 65 75 90 110 130 160) ;;
      100) NS=(50 75 90 100 110 125 150 175 200) ;;
      50) NS=(75 100 125 150 165 180 200 225) ;;
    esac
    for N in "${NS[@]}"; do
      echo "=== K=${K} N=${N} ===" && restart_aspnet $K $N
      collect --mode cliff-scan --N $N --K $K --T $N --runs 10
    done
  done
fi

if [[ "$MODE" == "k-sweep" ]]; then
  preflight

  run_K() {
    local K=$1; shift; local NS=("$@")
    echo "── K=${K}ms ($(date +%H:%M:%S)) ──"
    for N in "${NS[@]}"; do
      echo "=== K=${K} N=${N} ===" && restart_aspnet $K $N
      collect --mode k-sweep --N $N --K $K --T $N --runs 20
    done
    echo "── K=${K}ms done ($(date +%H:%M:%S)) ──"
  }

  case "$ONLY_K" in
    400) run_K 400 15 20 30 40 50 60 70 85 100 120 ;;
    200) run_K 200 30 45 60 75 90 110 130 160 ;;
    100) run_K 100 50 75 90 100 110 125 150 175 200 ;;
    50) run_K 50 75 100 125 150 165 180 200 225 260 300 350 400 ;;
    "")
      echo "Running all K groups. Allow ≥30 min cool-down between groups."
      for K in 400 200 100 50; do
        read -rp "Press ENTER to start K=${K}ms ..."
        bash "$0" k-sweep --only-K $K
      done
      ;;
    *) echo "Unknown K: $ONLY_K"; exit 1 ;;
  esac
fi

if [[ "$MODE" == "cross-val" ]]; then
  K=150
  PREDICTED=${PREDICTED_N:-90}
  NS=($(python3 -c "p=$PREDICTED; print(int(p*0.7), int(p), int(p*1.3), int(p*1.6))"))

  echo "▶ E1a cross-val (K=${K}ms, C=1, T_rem=10s)"
  echo "  Predicted N_safe ≈ ${PREDICTED} (from k-sweep formula)"
  echo "  N values: ${NS[*]}"

  for N in "${NS[@]}"; do
    echo "=== K=${K} N=${N} ===" && restart_aspnet $K $N
    collect --mode cross-val --N $N --K $K --T $N --runs 10
  done
fi

if [[ "$MODE" == "t-rem-sweep" ]]; then
  T_REM=${T_REM:-10}
  K=100
  preflight

  case "$T_REM" in
    5) CPU_S=10; NS=(25 30 35 40 45 50 55 65 75); TMODE="t-rem-5s" ;;
    20) CPU_S=25; NS=(120 140 160 175 190 210 230 260); TMODE="t-rem-20s" ;;
    20ext) CPU_S=25; NS=(60 70 75 80 85 90 100 110); TMODE="t-rem-20s" ;;
    *) echo "Unknown T_REM=${T_REM}. Use T_REM=5, T_REM=20, or T_REM=20ext (low-N extension)."; exit 1 ;;
  esac

  echo "▶ E1a t-rem-sweep (K=${K}ms, T_rem=${T_REM}, CPU_DURATION_S=${CPU_S}, 50 runs/cell)"
  [[ "$T_REM" =~ ^[0-9]+$ ]] && echo "  Predicted N_10 ≈ $((8000 * T_REM / 10 / K))"
  for N in "${NS[@]}"; do
    echo "=== t-rem-${T_REM}s K=${K} N=${N} ===" && restart_aspnet $K $N $CPU_S
    collect --mode $TMODE --N $N --K $K --T $N --runs 50 --cpu-s $CPU_S
  done
fi

if [[ "$MODE" == "c-dense" ]]; then
  C_VAL=${C_VAL:-2}
  K=100
  preflight

  case "$C_VAL" in
    2) CPUS=2.0; CPUSET="0,1"; NS=(140 160 175 190 200 215 230 250) ;;
    4) CPUS=4.0; CPUSET="0,1,2,3"; NS=(280 320 350 380 410 440 480 520) ;;
    *) echo "Unknown C_VAL=${C_VAL}. Use C_VAL=2 or C_VAL=4."; exit 1 ;;
  esac

  echo "▶ E1a c-dense (C=${C_VAL}, K=${K}ms, cpus=${CPUS}, cpuset=${CPUSET}, 50 runs/cell)"
  echo "  Predicted N_10 ≈ $((95 * C_VAL))  (= 95 × C)"
  for N in "${NS[@]}"; do
    echo "=== c-dense C=${C_VAL} K=${K} N=${N} ===" && restart_aspnet $K $N 15 $CPUS $CPUSET
    collect --mode c-dense --N $N --K $K --T $N --runs 50 --cores $C_VAL
  done

  echo "=== c-dense L1 check C=${C_VAL} K=${K} N=${C_VAL} ===" && restart_aspnet $K $C_VAL 15 $CPUS $CPUSET
  collect --mode c-dense --N $C_VAL --K $K --T $C_VAL --runs 20 --cores $C_VAL
fi

if [[ "$MODE" == "k-dense" ]]; then
  K_VAL=${K_VAL:-200}
  preflight

  case "$K_VAL" in
    200) NS=(45 50 55 60 65 70 75 80 85 90) ;;
    50) NS=(150 155 160 165 170 175 180 185 190 200) ;;
    400) NS=(13 15 17 19 21 23 25 28 32) ;;
    500) NS=(8 10 12 14 16 18 20 22 25 28) ;;
    *) echo "Unknown K_VAL=${K_VAL}. Supported: 50 200 400 500"; exit 1 ;;
  esac

  echo "▶ E1a k-dense (K=${K_VAL}ms, 50 runs/cell, N=[${NS[*]}])"
  for N in "${NS[@]}"; do
    echo "=== k-dense K=${K_VAL} N=${N} ===" && restart_aspnet $K_VAL $N
    collect --mode k-dense --N $N --K $K_VAL --T $N --runs 50
  done
fi

if [[ "$MODE" == "cliff-dense" ]]; then
  preflight
  K=100
  echo "▶ E1a cliff-dense (K=${K}ms, 50 runs/cell, N=80–175)"
  echo "  Purpose: characterise per-run failure probability as smooth function of N"
  for N in 80 85 90 95 100 105 110 115 120 125 130 140 150 160 175; do
    echo "=== cliff-dense K=${K} N=${N} ===" && restart_aspnet $K $N
    collect --mode cliff-dense --N $N --K $K --T $N --runs 50
  done
fi

if [[ "$MODE" == "webflux-sched" ]]; then
  K=100
  echo "▶ A1 within-WebFlux scheduler probe (K=${K}ms, C=1)"
  echo "── boundedElastic (idiomatic; expect flat ~100% across N) ──"
  for N in 1 8 32 100 175; do
    wait_quiet
    echo "=== be N=${N} ===" && restart_webflux $K boundedElastic
    collect --mode webflux-sched --N $N --K $K --T $N --runs 50 \
      --frameworks webflux --out e1f_webflux_be
  done
  echo "── immediate (probe; expect detection blackout at ALL N, incl. N=1) ──"
  for N in 1 8 32; do
    wait_quiet
    echo "=== imm N=${N} ===" && restart_webflux $K immediate
    collect --mode webflux-sched --N $N --K $K --T $N --runs 20 \
      --frameworks webflux --out e1f_webflux_imm
    docker compose -f "$REPO/docker-compose.yml" --profile spring-webflux stop spring-webflux >/dev/null 2>&1
  done
fi

if [[ "$MODE" == "go-cliff" ]]; then
  echo "▶ A2 Go cliff N-sweep (C=1)"
  for K in 200 100 50; do
    echo "── K=${K}ms ──"
    case $K in
      200) NS=(30 55 90 150) ;;
      100) NS=(50 95 150 200 300) ;;
      50) NS=(100 175 250 350) ;;
    esac
    for N in "${NS[@]}"; do
      wait_quiet
      echo "=== go K=${K} N=${N} ===" && restart_go $K
      collect --mode go-cliff --N $N --K $K --T $N --runs 50 \
        --frameworks go --out e1g_go_cliff
    done
  done
  echo "── Go latency probe (N=1 across K) ──"
  for K in 25 50 100 200 400; do
    wait_quiet
    echo "=== go-lat K=${K} N=1 ===" && restart_go $K
    collect --mode go-cliff --N 1 --K $K --T 1 --runs 30 \
      --frameworks go --out e1g_go_latency
  done
fi

if [[ "$MODE" == "blind" ]]; then
  K=300; CPUS=2.0; CPUSET="0,1"
  echo "▶ A3 blind prediction (C=2, K=${K}ms, cpuset=${CPUSET})"
  echo "  Predicted N_safe ≈ 73  (5499·2 / 300^0.880)"
  for N in 55 66 73 80 90; do
    wait_quiet
    echo "=== blind C=2 K=${K} N=${N} ===" && restart_aspnet $K $N 15 $CPUS $CPUSET
    collect --mode blind --N $N --K $K --T $N --runs 50 --cores 2 --out e1a_blind_C2_K300
  done
fi

if [[ "$MODE" == "noinject" ]]; then
  echo "▶ A4 no-injection K-sweep (C=1, THREAD_POOL_MIN=MAX=N)"
  for K in ${ONLY_K:-100 200 400}; do
    echo "── K=${K}ms (clean c=1.0 prediction N_safe ≈ $((10000 / K)); no-inject cliff sits above it) ──"
    case $K in
      100) NS=(110 130 150 175) ;;
      200) NS=(80 110 140 175) ;;
      400) NS=(45 65 90 120) ;;
    esac
    for N in "${NS[@]}"; do
      wait_quiet
      echo "=== noinject K=${K} N=${N} ===" && restart_aspnet_noinject $K $N
      collect --mode noinject --N $N --K $K --T $N --runs 50 --out e1a_noinject_K${K}
    done
  done
fi

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "E1a ${MODE} complete. Analyse:"
echo "  conda activate thesis-stats && python $REPO/tests/sq1/e1a_analyse.py"
