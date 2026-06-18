package com.example.spring.presentation;

import com.example.spring.cancellation.CancellationSource;
import com.example.spring.cancellation.CancelledException;
import com.example.spring.domain.ChainedService;
import com.example.spring.domain.CpuService;
import com.example.spring.domain.DbService;
import com.example.spring.domain.PipelineService;
import com.example.spring.observability.EventLog;
import com.example.spring.persistence.GhostWriteRepository;
import com.example.spring.persistence.TwoStepWriteRepository;
import jakarta.servlet.AsyncContext;
import jakarta.servlet.AsyncEvent;
import jakarta.servlet.AsyncListener;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.UUID;
import java.util.concurrent.Executor;
import java.util.concurrent.Executors;

@RestController
public class WorkController {

    private final Executor executor = Executors.newVirtualThreadPerTaskExecutor();

    private final CpuService cpuService;
    private final DbService dbService;
    private final PipelineService pipelineService;
    private final ChainedService chainedService;
    private final GhostWriteRepository ghostWriteRepo;
    private final TwoStepWriteRepository twoStepRepo;

    public WorkController(CpuService cpu, DbService db,
                          PipelineService pipeline, ChainedService chained,
                          GhostWriteRepository ghostWriteRepo,
                          TwoStepWriteRepository twoStepRepo) {
        this.cpuService = cpu;
        this.dbService = db;
        this.pipelineService = pipeline;
        this.chainedService = chained;
        this.ghostWriteRepo = ghostWriteRepo;
        this.twoStepRepo = twoStepRepo;
    }

    @GetMapping("/cpu")
    public void cpu(HttpServletRequest request, HttpServletResponse response) {
        dispatch(request, response, (req, source) -> cpuService.run(req, source));
    }

    @GetMapping("/db")
    public void db(HttpServletRequest request, HttpServletResponse response) {
        dispatch(request, response, (req, source) -> dbService.run(req, source));
    }

    @GetMapping("/pipeline")
    public void pipeline(HttpServletRequest request, HttpServletResponse response) {
        dispatch(request, response, (req, source) -> pipelineService.run(req, source));
    }

    @GetMapping("/async")
    public void asyncWait(HttpServletRequest request, HttpServletResponse response) {
        dispatch(request, response, (req, source) -> {
            EventLog.log(req, EventLog.Stage.SERVICE, "stage_entered");
            try {
                Thread.sleep(10_000);
                EventLog.log(req, EventLog.Stage.SERVICE, "stage_completed");
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                EventLog.log(req, EventLog.Stage.SERVICE, "cancellation_detected");
                throw new com.example.spring.cancellation.CancelledException();
            }
        });
    }

    @GetMapping("/chain")
    public void chain(HttpServletRequest request, HttpServletResponse response) {
        dispatch(request, response, (req, source) -> chainedService.run(req, source));
    }

    @GetMapping("/ghost-write")
    public void ghostWrite(HttpServletRequest request, HttpServletResponse response,
                           @RequestParam(name = "D", defaultValue = "1000") int dMs) {
        String req = generateRequestId();
        String reqId = UUID.randomUUID().toString();
        EventLog.log(req, EventLog.Stage.CONTROLLER, "request_received",
                "req_id=" + reqId + " D_ms=" + dMs);

        var source = new CancellationSource();
        var asyncCtx = request.startAsync(request, response);
        asyncCtx.setTimeout(-1);

        asyncCtx.addListener(new AsyncListener() {
            @Override
            public void onError(AsyncEvent event) {
                EventLog.log(req, EventLog.Stage.CONTROLLER, "client_disconnected");
                source.cancel();
            }
            @Override public void onTimeout(AsyncEvent event) { source.cancel(); }
            @Override public void onComplete(AsyncEvent event) {}
            @Override public void onStartAsync(AsyncEvent event) {}
        });

        executor.execute(() -> {
            source.setWorkerThread(Thread.currentThread());
            try {
                ghostWriteRepo.insert(req, reqId, dMs, source);
                EventLog.log(req, EventLog.Stage.CONTROLLER, "response_sent");
                asyncCtx.complete();
            } catch (CancelledException e) {
                EventLog.log(req, EventLog.Stage.CONTROLLER, "cancellation_propagated");
                asyncCtx.complete();
            } catch (Exception e) {
                asyncCtx.complete();
            }
        });
    }

    @GetMapping("/txn-write")
    public void txnWrite(HttpServletRequest request, HttpServletResponse response,
                         @RequestParam(name = "gap", defaultValue = "2000") int gapMs,
                         @RequestParam(name = "tx", defaultValue = "false") boolean tx) {
        String req = generateRequestId();
        String reqId = UUID.randomUUID().toString();
        EventLog.log(req, EventLog.Stage.CONTROLLER, "request_received",
                "req_id=" + reqId + " gap_ms=" + gapMs + " tx=" + tx);

        var source = new CancellationSource();
        var asyncCtx = request.startAsync(request, response);
        asyncCtx.setTimeout(-1);

        asyncCtx.addListener(new AsyncListener() {
            @Override
            public void onError(AsyncEvent event) {
                EventLog.log(req, EventLog.Stage.CONTROLLER, "client_disconnected");
                source.cancel();
            }
            @Override public void onTimeout(AsyncEvent event) { source.cancel(); }
            @Override public void onComplete(AsyncEvent event) {}
            @Override public void onStartAsync(AsyncEvent event) {}
        });

        executor.execute(() -> {
            source.setWorkerThread(Thread.currentThread());
            try {
                twoStepRepo.writeTwoSteps(req, reqId, gapMs, tx, source);
                EventLog.log(req, EventLog.Stage.CONTROLLER, "response_sent");
                asyncCtx.complete();
            } catch (CancelledException e) {
                EventLog.log(req, EventLog.Stage.CONTROLLER, "cancellation_propagated");
                asyncCtx.complete();
            } catch (Exception e) {
                asyncCtx.complete();
            }
        });
    }

    @FunctionalInterface
    private interface Work {
        void execute(String req, CancellationSource source);
    }

    private void dispatch(HttpServletRequest request, HttpServletResponse response, Work work) {
        String req = generateRequestId();
        EventLog.log(req, EventLog.Stage.CONTROLLER, "request_received");

        var source = new CancellationSource();
        var asyncCtx = request.startAsync(request, response);
        asyncCtx.setTimeout(-1);

        asyncCtx.addListener(new AsyncListener() {
            @Override
            public void onError(AsyncEvent event) {
                EventLog.log(req, EventLog.Stage.CONTROLLER, "client_disconnected");
                source.cancel();
            }
            @Override public void onTimeout(AsyncEvent event) { source.cancel(); }
            @Override public void onComplete(AsyncEvent event) {}
            @Override public void onStartAsync(AsyncEvent event) {}
        });

        executor.execute(() -> {
            source.setWorkerThread(Thread.currentThread());
            try {
                work.execute(req, source);
                EventLog.log(req, EventLog.Stage.CONTROLLER, "response_sent");
                asyncCtx.complete();
            } catch (CancelledException e) {
                EventLog.log(req, EventLog.Stage.CONTROLLER, "cancellation_propagated");
                asyncCtx.complete();
            } catch (Exception e) {
                asyncCtx.complete();
            }
        });
    }

    private static String generateRequestId() {
        return UUID.randomUUID().toString().replace("-", "").substring(0, 16).toUpperCase();
    }
}
