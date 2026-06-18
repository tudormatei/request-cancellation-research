#!/usr/bin/env bash

set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE="docker compose -f $REPO/docker-compose.yml"
PROBE="python $REPO/tests/sq3/e3_capacity_probe.py"
CSV="$REPO/experiments/sq3/e3c/e3_capacity_probe.csv"
LOG="$REPO/experiments/sq3/logs/capacity_sweep_$(date +%Y%m%d_%H%M%S).log"
mkdir -p "$(dirname "$LOG")" "$(dirname "$CSV")"
DURATION=${DURATION:-100}
TPMAX=200
YIELD_MS=100

warmup(){
  python - "$1" <<'PY' >/dev/null 2>&1 || true
import sys; sys.path.insert(0,'tests/sq3'); from _common import fire_sustained
fire_sustained(url=sys.argv[1], rate_rps=2, cancel_fraction=0.8, cancel_after_s=0.5, duration_s=15, window_s=30)
PY
}

log(){ echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

up_aspnet(){
  log "recreate aspnet POOL_SIZE=$1"
  THREAD_POOL_MAX=$TPMAX YIELD_INTERVAL_MS=$YIELD_MS POOL_SIZE=$1 \
    $COMPOSE --profile aspnet up -d --no-deps --force-recreate aspnet >>"$LOG" 2>&1
  sleep 15
}
up_webflux(){
  log "recreate webflux POOL_SIZE=$1"
  YIELD_INTERVAL_MS=$YIELD_MS POOL_SIZE=$1 \
    $COMPOSE --profile spring-webflux up -d --no-deps --force-recreate spring-webflux >>"$LOG" 2>&1
  sleep 20
}
stop_fw(){ docker stop "$1" >>"$LOG" 2>&1 || true; }

declare -A WF_X=( [10]="0.4 0.6 0.8" [20]="0.8 1.2 1.6" [30]="1.2 1.8 2.4" [40]="1.6 2.4 3.2" )
declare -A ASP_X=( [10]="1.5 2.5 3.5" [20]="3 5 7" [30]="4.5 7.5 10.5" [40]="6 10 14" )

if [[ -f "$CSV" ]]; then mv "$CSV" "${CSV%.csv}_$(date +%Y%m%d_%H%M%S).bak.csv"; fi

log "=== E3 capacity sweep start (duration=${DURATION}s/cell, ~$(( (32*(DURATION+15))/60 )) min) ==="
for POOL in 10 20 30 40; do
  stop_fw thesis_spring_webflux
  up_aspnet "$POOL"
  warmup "http://localhost:8081/db"
  for X in ${ASP_X[$POOL]}; do
    log "probe aspnet pool=$POOL X=$X"
    $PROBE --framework aspnet --pool "$POOL" --X "$X" --duration "$DURATION" >>"$LOG" 2>&1 \
      || log "  !! aspnet pool=$POOL X=$X FAILED"
    sleep 5
  done
  stop_fw thesis_aspnet
  up_webflux "$POOL"
  warmup "http://localhost:8083/db"
  for X in ${WF_X[$POOL]}; do
    log "probe webflux pool=$POOL X=$X"
    $PROBE --framework webflux --pool "$POOL" --X "$X" --duration "$DURATION" >>"$LOG" 2>&1 \
      || log "  !! webflux pool=$POOL X=$X FAILED"
    sleep 5
  done
done
log "=== sweep complete -> $CSV ==="
