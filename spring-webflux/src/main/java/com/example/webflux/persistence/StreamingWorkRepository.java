package com.example.webflux.persistence;

import com.example.webflux.observability.EventLog;
import org.springframework.r2dbc.core.DatabaseClient;
import org.springframework.stereotype.Repository;
import reactor.core.publisher.Mono;

import java.util.concurrent.atomic.AtomicInteger;

public interface StreamingWorkRepository {
    Mono<Void> stream(String req);
}

@Repository
class StreamingWorkRepositoryImpl implements StreamingWorkRepository {

    private final DatabaseClient databaseClient;

    StreamingWorkRepositoryImpl(DatabaseClient databaseClient) {
        this.databaseClient = databaseClient;
    }

    @Override
    public Mono<Void> stream(String req) {
        return Mono.defer(() -> {
            EventLog.log(req, EventLog.Stage.DB, "stream_started");
            AtomicInteger count = new AtomicInteger(0);
            return databaseClient
                    .sql("SELECT n, pg_sleep(0.0001) FROM generate_series(1, 30000) AS n")
                    .fetch()
                    .all()
                    .doOnNext(row -> {
                        int c = count.incrementAndGet();
                        if (c % 1_000 == 0)
                            EventLog.log(req, EventLog.Stage.DB, "rows_consumed", "count=" + c);
                    })
                    .doOnComplete(() -> EventLog.log(req, EventLog.Stage.DB, "stream_completed",
                            "total=" + count.get()))
                    .doOnCancel(() -> EventLog.log(req, EventLog.Stage.DB, "cancellation_detected",
                            "phase=stream rows_so_far=" + count.get()))
                    .then();
        });
    }
}
