package com.example.spring.domain;

import com.example.spring.cancellation.CancellationSource;
import com.example.spring.cancellation.CancelledException;
import com.example.spring.observability.EventLog;
import com.example.spring.persistence.WorkRepository;
import org.springframework.stereotype.Service;

public interface PipelineService {
    void run(String req, CancellationSource source);
}

@Service
class PipelineServiceImpl implements PipelineService {

    private static final int PREPARATION_SECONDS = 3;
    private static final long YIELD_INTERVAL_MS =
        Long.parseLong(System.getenv().getOrDefault("YIELD_INTERVAL_MS", "100"));

    private final WorkRepository repo;

    PipelineServiceImpl(WorkRepository repo) {
        this.repo = repo;
    }

    @Override
    public void run(String req, CancellationSource source) {
        EventLog.log(req, EventLog.Stage.SERVICE, "stage_entered");

        long start = System.currentTimeMillis();
        long iters = 0;
        long primes = 0;
        long candidate = 2;
        long lastYieldMs = start;

        while ((System.currentTimeMillis() - start) < PREPARATION_SECONDS * 1000L) {
            long now = System.currentTimeMillis();
            if (now - lastYieldMs >= YIELD_INTERVAL_MS) {
                lastYieldMs = now;
                if (source.isCancelled()) {
                    long elapsed = now - start;
                    EventLog.log(req, EventLog.Stage.SERVICE, "cancellation_detected",
                            "phase=preparation iters=" + iters + " primes=" + primes + " elapsed_ms=" + elapsed);
                    throw new CancelledException();
                }
                Thread.yield();
            }

            if (isPrime(candidate)) primes++;
            candidate++;
            iters++;
        }
        long elapsed = System.currentTimeMillis() - start;
        EventLog.log(req, EventLog.Stage.SERVICE, "preparation_completed",
                "iters=" + iters + " primes=" + primes + " elapsed_ms=" + elapsed);

        EventLog.log(req, EventLog.Stage.ASYNC_OP, "started");
        try {
            Thread.sleep(3_000);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            EventLog.log(req, EventLog.Stage.ASYNC_OP, "cancellation_detected");
            throw new CancelledException();
        }
        EventLog.log(req, EventLog.Stage.ASYNC_OP, "completed");

        repo.sleep(req, 5, source);

        EventLog.log(req, EventLog.Stage.SERVICE, "stage_completed");
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
