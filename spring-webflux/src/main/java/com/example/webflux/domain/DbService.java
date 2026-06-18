package com.example.webflux.domain;

import com.example.webflux.observability.EventLog;
import com.example.webflux.persistence.WorkRepository;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Mono;
import reactor.core.publisher.SignalType;

public interface DbService {
    Mono<Void> run(String req);
}

@Service
class DbServiceImpl implements DbService {

    private final WorkRepository repo;

    DbServiceImpl(WorkRepository repo) {
        this.repo = repo;
    }

    @Override
    public Mono<Void> run(String req) {
        EventLog.log(req, EventLog.Stage.SERVICE, "stage_entered");
        return repo.sleep(req, 10)
                .doOnSuccess(v -> EventLog.log(req, EventLog.Stage.SERVICE, "stage_completed"))
                .doOnCancel(() -> EventLog.log(req, EventLog.Stage.SERVICE, "cancellation_detected"))
                .doFinally(sig -> { if (sig == SignalType.CANCEL) EventLog.log(req, EventLog.Stage.SERVICE, "finally_cancel"); });
    }
}
