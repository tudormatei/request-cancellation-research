package com.example.spring.domain;

import com.example.spring.cancellation.CancellationSource;
import com.example.spring.cancellation.CancelledException;
import com.example.spring.observability.EventLog;
import com.example.spring.persistence.WorkRepository;
import org.springframework.stereotype.Service;

public interface ChainedService {
    void run(String req, CancellationSource source);
}

@Service
class ChainedServiceImpl implements ChainedService {

    private final WorkRepository repo;

    ChainedServiceImpl(WorkRepository repo) {
        this.repo = repo;
    }

    @Override
    public void run(String req, CancellationSource source) {
        EventLog.log(req, EventLog.Stage.SERVICE, "stage_entered");

        EventLog.log(req, EventLog.Stage.ASYNC_OP, "task_a_started");
        try {
            Thread.sleep(3_000);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            EventLog.log(req, EventLog.Stage.ASYNC_OP, "cancellation_detected", "task=a");
            throw new CancelledException();
        }
        EventLog.log(req, EventLog.Stage.ASYNC_OP, "task_a_completed");

        EventLog.log(req, EventLog.Stage.ASYNC_OP, "task_b_started");
        try {
            Thread.sleep(3_000);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            EventLog.log(req, EventLog.Stage.ASYNC_OP, "cancellation_detected", "task=b");
            throw new CancelledException();
        }
        EventLog.log(req, EventLog.Stage.ASYNC_OP, "task_b_completed");

        EventLog.log(req, EventLog.Stage.ASYNC_OP, "task_c_started");
        try {
            repo.sleep(req, 5, source);
        } catch (CancelledException e) {
            EventLog.log(req, EventLog.Stage.ASYNC_OP, "cancellation_detected", "task=c");
            throw e;
        }
        EventLog.log(req, EventLog.Stage.ASYNC_OP, "task_c_completed");

        EventLog.log(req, EventLog.Stage.SERVICE, "stage_completed");
    }
}
