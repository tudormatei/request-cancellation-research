package com.example.spring.domain;

import com.example.spring.cancellation.CancellationSource;
import com.example.spring.cancellation.CancelledException;
import com.example.spring.observability.EventLog;
import com.example.spring.persistence.WorkRepository;
import org.springframework.stereotype.Service;

public interface DbService {
    void run(String req, CancellationSource source);
}

@Service
class DbServiceImpl implements DbService {

    private final WorkRepository repo;

    DbServiceImpl(WorkRepository repo) {
        this.repo = repo;
    }

    @Override
    public void run(String req, CancellationSource source) {
        EventLog.log(req, EventLog.Stage.SERVICE, "stage_entered");

        try {
            repo.sleep(req, 10, source);
            EventLog.log(req, EventLog.Stage.SERVICE, "stage_completed");
        } catch (CancelledException e) {
            EventLog.log(req, EventLog.Stage.SERVICE, "cancellation_detected");
            throw e;
        }
    }
}
