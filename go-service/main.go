package main

import (
	"fmt"
	"net/http"
	"os"
	"runtime"
	"strconv"
	"sync/atomic"
	"time"
)

const (
	stageController = "controller"
	stageServer     = "server"
	stageService    = "service"
)

var (
	durationSeconds = envInt("CPU_DURATION_S", 15)
	yieldIntervalMs = int64(envInt("YIELD_INTERVAL_MS", 100))
	reqCounter      uint64
)

func logEvent(req, stage, event, detail string) {
	ts := time.Now().UnixMilli()
	if detail == "" {
		fmt.Printf("ts=%d req=%s stage=%s event=%s\n", ts, req, stage, event)
	} else {
		fmt.Printf("ts=%d req=%s stage=%s event=%s detail=%s\n", ts, req, stage, event, detail)
	}
}

func envInt(key string, def int) int {
	if v, ok := os.LookupEnv(key); ok {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}

func isPrime(n int64) bool {
	if n < 2 {
		return false
	}
	if n == 2 {
		return true
	}
	if n%2 == 0 {
		return false
	}
	for i := int64(3); i*i <= n; i += 2 {
		if n%i == 0 {
			return false
		}
	}
	return true
}

func cpuHandler(w http.ResponseWriter, r *http.Request) {
	req := "go-" + strconv.FormatUint(atomic.AddUint64(&reqCounter, 1), 10)
	ctx := r.Context()

	clientTs := r.URL.Query().Get("ts")
	if clientTs != "" {
		logEvent(req, stageController, "request_received", "client_ts="+clientTs)
	} else {
		logEvent(req, stageController, "request_received", "")
	}

	go func() {
		<-ctx.Done()
		logEvent(req, stageServer, "disconnect_detected", "")
	}()

	logEvent(req, stageService, "stage_entered", "")
	logEvent(req, stageService, "work_started", "")

	start := time.Now()
	deadline := start.Add(time.Duration(durationSeconds) * time.Second)
	lastCheck := start
	var iters, primes, candidate int64 = 0, 0, 2

	for time.Now().Before(deadline) {
		now := time.Now()
		if now.Sub(lastCheck).Milliseconds() >= yieldIntervalMs {
			lastCheck = now
			select {
			case <-ctx.Done():
				elapsed := now.Sub(start).Milliseconds()
				logEvent(req, stageService, "cancellation_detected",
					fmt.Sprintf("iters=%d primes=%d elapsed_ms=%d", iters, primes, elapsed))
				return
			default:
			}
		}
		if isPrime(candidate) {
			primes++
		}
		candidate++
		iters++
	}

	elapsed := time.Since(start).Milliseconds()
	logEvent(req, stageService, "work_completed",
		fmt.Sprintf("iters=%d primes=%d elapsed_ms=%d", iters, primes, elapsed))
	logEvent(req, stageController, "response_sent", "")
	w.WriteHeader(http.StatusOK)
}

func main() {
	port := os.Getenv("SERVER_PORT")
	if port == "" {
		port = "8080"
	}
	fmt.Printf("go-service ready yield_interval_ms=%d cpu_duration_s=%d gomaxprocs=%d num_cpu=%d\n",
		yieldIntervalMs, durationSeconds, runtime.GOMAXPROCS(0), runtime.NumCPU())

	mux := http.NewServeMux()
	mux.HandleFunc("/cpu", cpuHandler)
	if err := http.ListenAndServe(":"+port, mux); err != nil {
		fmt.Fprintln(os.Stderr, "server error:", err)
		os.Exit(1)
	}
}
