package com.example.webflux.persistence;

import com.example.webflux.observability.EventLog;
import org.springframework.r2dbc.core.DatabaseClient;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.reactive.TransactionalOperator;
import reactor.core.publisher.Mono;

import java.time.Duration;

public interface TwoStepWriteRepository {
    Mono<Void> writeTwoSteps(String req, String reqId, int gapMs, boolean txnMode);
}

@Repository
class TwoStepWriteRepositoryImpl implements TwoStepWriteRepository {

    private final DatabaseClient db;
    private final TransactionalOperator txOperator;

    TwoStepWriteRepositoryImpl(DatabaseClient db, TransactionalOperator txOperator) {
        this.db = db;
        this.txOperator = txOperator;
    }

    @Override
    public Mono<Void> writeTwoSteps(String req, String reqId, int gapMs, boolean txnMode) {
        Mono<Void> chain = insertStep(req, reqId, 1)
                .then(Mono.fromRunnable(() ->
                        EventLog.log(req, EventLog.Stage.DB, "gap_started", "gap_ms=" + gapMs + " tx=" + txnMode)))
                .then(Mono.delay(Duration.ofMillis(gapMs))
                        .doOnCancel(() -> EventLog.log(req, EventLog.Stage.DB, "cancellation_detected", "phase=gap"))
                        .then())
                .then(Mono.fromRunnable(() -> EventLog.log(req, EventLog.Stage.DB, "gap_completed")))
                .then(insertStep(req, reqId, 2));

        if (txnMode) {
            return txOperator.transactional(chain)
                    .doOnCancel(() -> EventLog.log(req, EventLog.Stage.DB, "cancellation_detected", "phase=txn"));
        }
        return chain;
    }

    private Mono<Void> insertStep(String req, String reqId, int step) {
        return Mono.defer(() -> {
            EventLog.log(req, EventLog.Stage.DB, "insert_started", "step=" + step);
            return db
                    .sql("INSERT INTO txn_writes(req_id, step) VALUES (:reqId::uuid, :step) /* req=" + reqId + " */")
                    .bind("reqId", reqId)
                    .bind("step", step)
                    .fetch()
                    .rowsUpdated()
                    .doOnSuccess(n -> EventLog.log(req, EventLog.Stage.DB, "insert_completed", "step=" + step))
                    .then();
        });
    }
}
