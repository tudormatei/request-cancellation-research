package com.example.webflux.presentation;

import com.example.webflux.domain.ChainedService;
import com.example.webflux.domain.CpuService;
import com.example.webflux.domain.DbService;
import com.example.webflux.domain.PipelineService;
import com.example.webflux.grpc.DownstreamServiceGrpc;
import com.example.webflux.grpc.SlowRequest;
import com.example.webflux.grpc.SlowResponse;
import com.example.webflux.observability.EventLog;
import com.example.webflux.persistence.GhostWriteRepository;
import com.example.webflux.persistence.StreamingWorkRepository;
import com.example.webflux.persistence.TwoStepWriteRepository;
import io.grpc.CallOptions;
import io.grpc.ClientCall;
import io.grpc.ManagedChannel;
import io.grpc.Metadata;
import io.grpc.Status;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.time.Duration;
import java.util.UUID;

@RestController
public class WorkController {

    private final CpuService cpuService;
    private final DbService dbService;
    private final PipelineService pipelineService;
    private final ChainedService chainedService;
    private final StreamingWorkRepository streamingRepo;
    private final GhostWriteRepository ghostWriteRepo;
    private final TwoStepWriteRepository twoStepRepo;
    private final WebClient downstreamWebClient;
    private final ManagedChannel downstreamGrpcChannel;

    public WorkController(CpuService cpu, DbService db,
                          PipelineService pipeline, ChainedService chained,
                          StreamingWorkRepository streamingRepo,
                          GhostWriteRepository ghostWriteRepo,
                          TwoStepWriteRepository twoStepRepo,
                          WebClient downstreamWebClient,
                          ManagedChannel downstreamGrpcChannel) {
        this.cpuService = cpu;
        this.dbService = db;
        this.pipelineService = pipeline;
        this.chainedService = chained;
        this.streamingRepo = streamingRepo;
        this.ghostWriteRepo = ghostWriteRepo;
        this.twoStepRepo = twoStepRepo;
        this.downstreamWebClient = downstreamWebClient;
        this.downstreamGrpcChannel = downstreamGrpcChannel;
    }

    @GetMapping("/cpu")
    public Mono<Void> cpu(@RequestParam(required = false) String ts) {
        String req = generateRequestId();
        EventLog.log(req, EventLog.Stage.CONTROLLER, "request_received", ts != null ? "client_ts=" + ts : null);
        return cpuService.run(req)
                .doOnSuccess(v -> EventLog.log(req, EventLog.Stage.CONTROLLER, "response_sent"))
                .doOnCancel(() -> EventLog.log(req, EventLog.Stage.CONTROLLER, "cancellation_propagated"))
                .doOnCancel(() -> EventLog.log(req, EventLog.Stage.NETTY, "disconnect_detected"));
    }

    @GetMapping("/db")
    public Mono<Void> db(@RequestParam(required = false) String ts) {
        String req = generateRequestId();
        EventLog.log(req, EventLog.Stage.CONTROLLER, "request_received", ts != null ? "client_ts=" + ts : null);
        return dbService.run(req)
                .doOnSuccess(v -> EventLog.log(req, EventLog.Stage.CONTROLLER, "response_sent"))
                .doOnCancel(() -> EventLog.log(req, EventLog.Stage.CONTROLLER, "cancellation_propagated"))
                .doOnCancel(() -> EventLog.log(req, EventLog.Stage.NETTY, "disconnect_detected"));
    }

    @GetMapping("/pipeline")
    public Mono<Void> pipeline(@RequestParam(required = false) String ts) {
        String req = generateRequestId();
        EventLog.log(req, EventLog.Stage.CONTROLLER, "request_received", ts != null ? "client_ts=" + ts : null);
        return pipelineService.run(req)
                .doOnSuccess(v -> EventLog.log(req, EventLog.Stage.CONTROLLER, "response_sent"))
                .doOnCancel(() -> EventLog.log(req, EventLog.Stage.CONTROLLER, "cancellation_propagated"))
                .doOnCancel(() -> EventLog.log(req, EventLog.Stage.NETTY, "disconnect_detected"));
    }

    @GetMapping("/async")
    public Mono<Void> asyncWait(@RequestParam(required = false) String ts) {
        String req = generateRequestId();
        EventLog.log(req, EventLog.Stage.CONTROLLER, "request_received", ts != null ? "client_ts=" + ts : null);
        return Mono.delay(Duration.ofSeconds(10))
                .then()
                .doOnSuccess(v -> EventLog.log(req, EventLog.Stage.CONTROLLER, "response_sent"))
                .doOnCancel(() -> EventLog.log(req, EventLog.Stage.CONTROLLER, "cancellation_propagated"))
                .doOnCancel(() -> EventLog.log(req, EventLog.Stage.NETTY, "disconnect_detected"));
    }

    @GetMapping("/chain")
    public Mono<Void> chain(@RequestParam(required = false) String ts) {
        String req = generateRequestId();
        EventLog.log(req, EventLog.Stage.CONTROLLER, "request_received", ts != null ? "client_ts=" + ts : null);
        return chainedService.run(req)
                .doOnSuccess(v -> EventLog.log(req, EventLog.Stage.CONTROLLER, "response_sent"))
                .doOnCancel(() -> EventLog.log(req, EventLog.Stage.CONTROLLER, "cancellation_propagated"))
                .doOnCancel(() -> EventLog.log(req, EventLog.Stage.NETTY, "disconnect_detected"));
    }

    @GetMapping("/stream-db")
    public Mono<Void> streamDb(@RequestParam(required = false) String ts) {
        String req = generateRequestId();
        EventLog.log(req, EventLog.Stage.CONTROLLER, "request_received", ts != null ? "client_ts=" + ts : null);
        return streamingRepo.stream(req)
                .doOnSuccess(v -> EventLog.log(req, EventLog.Stage.CONTROLLER, "response_sent"))
                .doOnCancel(() -> EventLog.log(req, EventLog.Stage.CONTROLLER, "cancellation_propagated"))
                .doOnCancel(() -> EventLog.log(req, EventLog.Stage.NETTY, "disconnect_detected"));
    }

    @GetMapping("/outbound")
    public Mono<Void> outbound(@RequestParam(required = false) String ts) {
        String req = generateRequestId();
        EventLog.log(req, EventLog.Stage.CONTROLLER, "request_received", ts != null ? "client_ts=" + ts : null);
        EventLog.log(req, EventLog.Stage.ASYNC_OP, "outbound_started");
        return downstreamWebClient.get()
                .uri("/slow?delay=10")
                .header("X-Req-ID", req)
                .retrieve()
                .bodyToMono(String.class)
                .doOnSuccess(v -> EventLog.log(req, EventLog.Stage.ASYNC_OP, "outbound_completed"))
                .doOnCancel(() -> EventLog.log(req, EventLog.Stage.ASYNC_OP, "cancellation_detected",
                        "source=outbound"))
                .then()
                .doOnSuccess(v -> EventLog.log(req, EventLog.Stage.CONTROLLER, "response_sent"))
                .doOnCancel(() -> EventLog.log(req, EventLog.Stage.CONTROLLER, "cancellation_propagated"))
                .doOnCancel(() -> EventLog.log(req, EventLog.Stage.NETTY, "disconnect_detected"));
    }

    @GetMapping("/outbound-grpc")
    public Mono<Void> outboundGrpc(@RequestParam(required = false) String ts) {
        String req = generateRequestId();
        EventLog.log(req, EventLog.Stage.CONTROLLER, "request_received", ts != null ? "client_ts=" + ts : null);
        EventLog.log(req, EventLog.Stage.ASYNC_OP, "outbound_grpc_started");

        return Mono.<Void>create(sink -> {
            SlowRequest request = SlowRequest.newBuilder()
                    .setReqId(req)
                    .setDelaySeconds(10)
                    .build();

            ClientCall<SlowRequest, SlowResponse> call =
                    downstreamGrpcChannel.newCall(
                            DownstreamServiceGrpc.getSlowCallMethod(),
                            CallOptions.DEFAULT
                    );

            call.start(new ClientCall.Listener<SlowResponse>() {
                @Override
                public void onMessage(SlowResponse message) {
                    call.request(1);
                }

                @Override
                public void onClose(Status status, Metadata trailers) {
                    if (status.isOk()) {
                        EventLog.log(req, EventLog.Stage.ASYNC_OP, "outbound_grpc_completed");
                        sink.success(null);
                    } else if (status.getCode() == Status.Code.CANCELLED) {
                        sink.success(null);
                    } else {
                        sink.error(status.asException());
                    }
                }
            }, new Metadata());

            call.sendMessage(request);
            call.halfClose();
            call.request(1);

            sink.onCancel(() -> {
                EventLog.log(req, EventLog.Stage.ASYNC_OP, "cancellation_detected",
                        "source=outbound_grpc");
                call.cancel("inbound client disconnected", null);
            });
        })
        .doOnSuccess(v -> EventLog.log(req, EventLog.Stage.CONTROLLER, "response_sent"))
        .doOnCancel(() -> EventLog.log(req, EventLog.Stage.CONTROLLER, "cancellation_propagated"))
        .doOnCancel(() -> EventLog.log(req, EventLog.Stage.NETTY, "disconnect_detected"));
    }

    @GetMapping("/ghost-write")
    public Mono<Void> ghostWrite(@RequestParam(required = false) String ts,
                                 @RequestParam(name = "D", required = false, defaultValue = "1000") int dMs) {
        String req = generateRequestId();
        String reqId = UUID.randomUUID().toString();
        EventLog.log(req, EventLog.Stage.CONTROLLER, "request_received",
                "req_id=" + reqId + (ts != null ? " client_ts=" + ts : ""));
        return ghostWriteRepo.insert(req, reqId, dMs)
                .doOnSuccess(v -> EventLog.log(req, EventLog.Stage.CONTROLLER, "response_sent"))
                .doOnCancel(() -> EventLog.log(req, EventLog.Stage.CONTROLLER, "cancellation_propagated",
                        "outer=None inner=None sql_state=None"))
                .doOnCancel(() -> EventLog.log(req, EventLog.Stage.NETTY, "disconnect_detected"));
    }

    @GetMapping("/txn-write")
    public Mono<Void> txnWrite(@RequestParam(name = "gap", required = false, defaultValue = "2000") int gapMs,
                               @RequestParam(name = "tx", required = false, defaultValue = "false") boolean tx) {
        String req = generateRequestId();
        String reqId = UUID.randomUUID().toString();
        EventLog.log(req, EventLog.Stage.CONTROLLER, "request_received",
                "req_id=" + reqId + " gap_ms=" + gapMs + " tx=" + tx);
        return twoStepRepo.writeTwoSteps(req, reqId, gapMs, tx)
                .doOnSuccess(v -> EventLog.log(req, EventLog.Stage.CONTROLLER, "response_sent"))
                .doOnCancel(() -> EventLog.log(req, EventLog.Stage.CONTROLLER, "cancellation_propagated"))
                .doOnCancel(() -> EventLog.log(req, EventLog.Stage.NETTY, "disconnect_detected"));
    }

    private static String generateRequestId() {
        return UUID.randomUUID().toString().replace("-", "").substring(0, 16).toUpperCase();
    }
}
