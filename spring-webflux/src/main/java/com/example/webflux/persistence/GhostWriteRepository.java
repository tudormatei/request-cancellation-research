package com.example.webflux.persistence;

import com.example.webflux.observability.EventLog;
import org.springframework.r2dbc.core.DatabaseClient;
import org.springframework.stereotype.Repository;
import reactor.core.publisher.Mono;

public interface GhostWriteRepository {
    Mono<Void> insert(String req, String reqId, int dMs);
}

@Repository
class GhostWriteRepositoryImpl implements GhostWriteRepository {

    private final DatabaseClient databaseClient;

    GhostWriteRepositoryImpl(DatabaseClient databaseClient) {
        this.databaseClient = databaseClient;
    }

    @Override
    public Mono<Void> insert(String req, String reqId, int dMs) {
        double dSeconds = dMs / 1000.0;
        return Mono.defer(() -> {
            EventLog.log(req, EventLog.Stage.DB, "insert_started", "D_ms=" + dMs);
            return databaseClient
                    .sql("INSERT INTO ghost_writes(req_id, ts) SELECT :reqId::uuid, NOW() FROM pg_sleep(:dSeconds)")
                    .bind("reqId", reqId)
                    .bind("dSeconds", dSeconds)
                    .fetch()
                    .rowsUpdated()
                    .doOnSuccess(n -> EventLog.log(req, EventLog.Stage.DB, "insert_completed"))
                    .doOnCancel(() -> EventLog.log(req, EventLog.Stage.DB, "cancellation_detected", "phase=insert"))
                    .then();
        });
    }
}
