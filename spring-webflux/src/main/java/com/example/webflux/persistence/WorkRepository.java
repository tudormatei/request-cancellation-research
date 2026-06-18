package com.example.webflux.persistence;

import com.example.webflux.observability.EventLog;
import org.springframework.r2dbc.core.DatabaseClient;
import org.springframework.stereotype.Repository;
import reactor.core.publisher.Mono;
import reactor.core.publisher.SignalType;

public interface WorkRepository {
    Mono<Void> sleep(String req, int seconds);
}

@Repository
class WorkRepositoryImpl implements WorkRepository {

    private final DatabaseClient databaseClient;

    WorkRepositoryImpl(DatabaseClient databaseClient) {
        this.databaseClient = databaseClient;
    }

    @Override
    public Mono<Void> sleep(String req, int seconds) {
        return Mono.defer(() -> {
            EventLog.log(req, EventLog.Stage.DB, "query_started", "pg_sleep=" + seconds + "s");
            return databaseClient
                    .sql("SELECT pg_sleep(:seconds)")
                    .bind("seconds", seconds)
                    .fetch()
                    .one()
                    .doOnSuccess(v -> EventLog.log(req, EventLog.Stage.DB, "query_completed"))
                    .doOnCancel(() -> EventLog.log(req, EventLog.Stage.DB, "cancellation_detected", "phase=query"))
                    .doFinally(sig -> { if (sig == SignalType.CANCEL) EventLog.log(req, EventLog.Stage.DB, "finally_cancel", "phase=query"); })
                    .then();
        });
    }
}
