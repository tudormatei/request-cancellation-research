package com.example.webflux.domain;

import com.example.webflux.observability.EventLog;
import com.example.webflux.persistence.WorkRepository;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Mono;

import java.time.Duration;
import java.util.concurrent.atomic.AtomicBoolean;

public interface PipelineService {
    Mono<Void> run(String req);
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
    public Mono<Void> run(String req) {
        EventLog.log(req, EventLog.Stage.SERVICE, "stage_entered");

        Mono<Void> cpuStage = Mono.<Void>create(sink -> {
            AtomicBoolean cancelled = new AtomicBoolean(false);
            sink.onCancel(() -> cancelled.set(true));

            long start = System.currentTimeMillis();
            long iters = 0;
            long primes = 0;
            long candidate = 2;
            long lastCheckMs = start;

            while (System.currentTimeMillis() - start < PREPARATION_SECONDS * 1000L) {
                long now = System.currentTimeMillis();
                if (now - lastCheckMs >= YIELD_INTERVAL_MS) {
                    lastCheckMs = now;
                    if (cancelled.get()) {
                        long elapsed = now - start;
                        EventLog.log(req, EventLog.Stage.SERVICE, "cancellation_detected",
                                "phase=preparation iters=" + iters + " primes=" + primes + " elapsed_ms=" + elapsed);
                        return;
                    }
                }
                if (isPrime(candidate)) primes++;
                candidate++;
                iters++;
            }
            long elapsed = System.currentTimeMillis() - start;
            EventLog.log(req, EventLog.Stage.SERVICE, "preparation_completed",
                    "iters=" + iters + " primes=" + primes + " elapsed_ms=" + elapsed);
            sink.success();
        }).subscribeOn(SchedulerConfig.CPU);

        Mono<Void> asyncStage = Mono.defer(() -> {
            EventLog.log(req, EventLog.Stage.ASYNC_OP, "started");
            return Mono.delay(Duration.ofSeconds(3))
                    .doOnCancel(() -> EventLog.log(req, EventLog.Stage.ASYNC_OP, "cancellation_detected"))
                    .doOnSuccess(v -> EventLog.log(req, EventLog.Stage.ASYNC_OP, "completed"))
                    .then();
        });

        return cpuStage
                .then(asyncStage)
                .then(repo.sleep(req, 5))
                .doOnSuccess(v -> EventLog.log(req, EventLog.Stage.SERVICE, "stage_completed"));
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
