package com.example.webflux.domain;

import com.example.webflux.observability.EventLog;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Mono;

import java.util.concurrent.atomic.AtomicBoolean;

public interface CpuService {
    Mono<Void> run(String req);
}

@Service
class CpuServiceImpl implements CpuService {

    private static final int DURATION_SECONDS = 15;
    private static final long YIELD_INTERVAL_MS =
        Long.parseLong(System.getenv().getOrDefault("YIELD_INTERVAL_MS", "100"));

    @Override
    public Mono<Void> run(String req) {
        return Mono.<Void>create(sink -> {
            AtomicBoolean cancelled = new AtomicBoolean(false);
            sink.onCancel(() -> cancelled.set(true));

            EventLog.log(req, EventLog.Stage.SERVICE, "stage_entered");

            long start = System.currentTimeMillis();
            long iters = 0;
            long primes = 0;
            long candidate = 2;
            long lastCheckMs = start;

            EventLog.log(req, EventLog.Stage.SERVICE, "work_started");

            while (System.currentTimeMillis() - start < DURATION_SECONDS * 1000L) {
                long now = System.currentTimeMillis();
                if (now - lastCheckMs >= YIELD_INTERVAL_MS) {
                    lastCheckMs = now;
                    if (cancelled.get()) {
                        long elapsed = now - start;
                        EventLog.log(req, EventLog.Stage.SERVICE, "cancellation_detected",
                                "iters=" + iters + " primes=" + primes + " elapsed_ms=" + elapsed);
                        return;
                    }
                }

                if (isPrime(candidate)) primes++;
                candidate++;
                iters++;
            }

            long elapsed = System.currentTimeMillis() - start;
            EventLog.log(req, EventLog.Stage.SERVICE, "work_completed",
                    "iters=" + iters + " primes=" + primes + " elapsed_ms=" + elapsed);
            sink.success();
        }).subscribeOn(SchedulerConfig.CPU);
    }

    private static boolean isPrime(long n) {
        if (n < 2) return false;
        if (n == 2) return true;
        if (n % 2 == 0) return false;
        for (long i = 3; i * i <= n; i += 2)
            if (n % i == 0) return false;
        return true;
    }
}
