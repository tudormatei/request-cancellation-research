package com.example.webflux.domain;

import com.example.webflux.observability.EventLog;
import com.example.webflux.persistence.WorkRepository;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Mono;

import java.time.Duration;

public interface ChainedService {
    Mono<Void> run(String req);
}

@Service
class ChainedServiceImpl implements ChainedService {

    private final WorkRepository repo;

    ChainedServiceImpl(WorkRepository repo) {
        this.repo = repo;
    }

    @Override
    public Mono<Void> run(String req) {
        EventLog.log(req, EventLog.Stage.SERVICE, "stage_entered");

        Mono<Void> taskA = Mono.defer(() -> {
            EventLog.log(req, EventLog.Stage.ASYNC_OP, "task_a_started");
            return Mono.delay(Duration.ofSeconds(3))
                    .doOnCancel(() -> EventLog.log(req, EventLog.Stage.ASYNC_OP, "cancellation_detected", "task=a"))
                    .then();
        });

        Mono<Void> taskB = Mono.defer(() -> {
            EventLog.log(req, EventLog.Stage.ASYNC_OP, "task_b_started");
            return Mono.delay(Duration.ofSeconds(3))
                    .doOnCancel(() -> EventLog.log(req, EventLog.Stage.ASYNC_OP, "cancellation_detected", "task=b"))
                    .then();
        });

        Mono<Void> taskC = Mono.defer(() -> {
            EventLog.log(req, EventLog.Stage.ASYNC_OP, "task_c_started");
            return repo.sleep(req, 5)
                    .doOnCancel(() -> EventLog.log(req, EventLog.Stage.ASYNC_OP, "cancellation_detected", "task=c"));
        });

        return taskA
                .doOnSuccess(v -> EventLog.log(req, EventLog.Stage.ASYNC_OP, "task_a_completed"))
                .then(taskB)
                .doOnSuccess(v -> EventLog.log(req, EventLog.Stage.ASYNC_OP, "task_b_completed"))
                .then(taskC)
                .doOnSuccess(v -> EventLog.log(req, EventLog.Stage.ASYNC_OP, "task_c_completed"))
                .doOnSuccess(v -> EventLog.log(req, EventLog.Stage.SERVICE, "stage_completed"));
    }
}
