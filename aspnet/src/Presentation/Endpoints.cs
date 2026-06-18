using Downstream.Grpc;
using Grpc.Net.Client;
using src.Domain;
using src.Persistence;
using static src.Observability.EventLog;

namespace src.Presentation;


public static class Endpoints
{
    public static void MapWorkEndpoints(this WebApplication app)
    {
        app.MapGet("/ghost-write", async (IGhostWriteRepository repo, CancellationToken ct, HttpContext ctx) =>
        {
            var req = ctx.TraceIdentifier;
            var reqId = Guid.NewGuid();
            var dMs = int.TryParse(ctx.Request.Query["D"].FirstOrDefault(), out var d) ? d : 1000;

            Log(req, Stage.Controller, "request_received", $"req_id={reqId} D_ms={dMs}");
            ct.Register(() => Log(req, Stage.Kestrel, "disconnect_detected"));

            try
            {var sw      = Stopwatch.StartNew();
        long iters  = 0;
        long primes = 0;
        long candidate = 2;
                await repo.InsertAsync(req, reqId, dMs, ct);
                Log(req, Stage.Controller, "response_sent");
                return Results.Ok(new { committed = true, req_id = reqId });
            }
            catch (OperationCanceledException oce)
            {
                var inner = oce.InnerException;
                string detail;
                if (inner is Npgsql.PostgresException pgEx)
                    detail = $"outer=OperationCanceledException inner=PostgresException sql_state={pgEx.SqlState}";
                else if (inner is not null)
                    detail = $"outer=OperationCanceledException inner={inner.GetType().Name} sql_state=None";
                else
                    detail = "outer=OperationCanceledException inner=None sql_state=None";

                Log(req, Stage.Controller, "cancellation_propagated", detail);
                return Results.Empty;
            }
        });


        app.MapGet("/txn-write", async (ITwoStepWriteRepository repo, CancellationToken ct, HttpContext ctx) =>
        {
            var req = ctx.TraceIdentifier;
            var reqId = Guid.NewGuid();
            var gapMs = int.TryParse(ctx.Request.Query["gap"].FirstOrDefault(), out var g) ? g : 2000;
            var txn = bool.TryParse(ctx.Request.Query["tx"].FirstOrDefault(), out var t) && t;

            Log(req, Stage.Controller, "request_received", $"req_id={reqId} gap_ms={gapMs} tx={txn}");
            ct.Register(() => Log(req, Stage.Kestrel, "disconnect_detected"));

            try
            {
                await repo.WriteTwoStepsAsync(req, reqId, gapMs, txn, ct);
                Log(req, Stage.Controller, "response_sent");
                return Results.Ok(new { committed = true, req_id = reqId });
            }
            catch (OperationCanceledException oce)
            {
                var inner = oce.InnerException;
                string detail = inner is Npgsql.PostgresException pgEx
                    ? $"outer=OperationCanceledException inner=PostgresException sql_state={pgEx.SqlState}"
                    : inner is not null
                        ? $"outer=OperationCanceledException inner={inner.GetType().Name} sql_state=None"
                        : "outer=OperationCanceledException inner=None sql_state=None";
                Log(req, Stage.Controller, "cancellation_propagated", detail);
                return Results.Empty;
            }
        });


        app.MapGet("/cpu", async (ICpuService cpu, CancellationToken ct, HttpContext ctx) =>
        {
            var req = ctx.TraceIdentifier;
            var clientTs = ctx.Request.Query["ts"].FirstOrDefault();
            Log(req, Stage.Controller, "request_received", clientTs is not null ? $"client_ts={clientTs}" : null);
            ct.Register(() => Log(req, Stage.Kestrel, "disconnect_detected"));

            try
            {
                await cpu.RunAsync(req, ct);
                Log(req, Stage.Controller, "response_sent");
                return Results.Ok();
            }
            catch (OperationCanceledException)
            {
                Log(req, Stage.Controller, "cancellation_propagated");
                return Results.Empty;
            }
        });

        app.MapGet("/db", async (IDbService db, CancellationToken ct, HttpContext ctx) =>
        {
            var req = ctx.TraceIdentifier;
            var clientTs = ctx.Request.Query["ts"].FirstOrDefault();
            Log(req, Stage.Controller, "request_received", clientTs is not null ? $"client_ts={clientTs}" : null);
            ct.Register(() => Log(req, Stage.Kestrel, "disconnect_detected"));

            try
            {
                await db.RunAsync(req, ct);
                Log(req, Stage.Controller, "response_sent");
                return Results.Ok();
            }
            catch (OperationCanceledException)
            {
                Log(req, Stage.Controller, "cancellation_propagated");
                return Results.Empty;
            }
        });

        app.MapGet("/pipeline", async (IPipelineService pipeline, CancellationToken ct, HttpContext ctx) =>
        {
            var req = ctx.TraceIdentifier;
            var clientTs = ctx.Request.Query["ts"].FirstOrDefault();
            Log(req, Stage.Controller, "request_received", clientTs is not null ? $"client_ts={clientTs}" : null);
            ct.Register(() => Log(req, Stage.Kestrel, "disconnect_detected"));

            try
            {
                await pipeline.RunAsync(req, ct);
                Log(req, Stage.Controller, "response_sent");
                return Results.Ok();
            }
            catch (OperationCanceledException)
            {
                Log(req, Stage.Controller, "cancellation_propagated");
                return Results.Empty;
            }
        });

        app.MapGet("/async", async (CancellationToken ct, HttpContext ctx) =>
        {
            var req = ctx.TraceIdentifier;
            var clientTs = ctx.Request.Query["ts"].FirstOrDefault();
            Log(req, Stage.Controller, "request_received", clientTs is not null ? $"client_ts={clientTs}" : null);
            ct.Register(() => Log(req, Stage.Kestrel, "disconnect_detected"));

            try
            {
                await Task.Delay(10_000, ct);
                Log(req, Stage.Controller, "response_sent");
                return Results.Ok();
            }
            catch (OperationCanceledException)
            {
                Log(req, Stage.Controller, "cancellation_propagated");
                return Results.Empty;
            }
        });

        app.MapGet("/chain", async (IChainedService chain, CancellationToken ct, HttpContext ctx) =>
        {
            var req = ctx.TraceIdentifier;
            var clientTs = ctx.Request.Query["ts"].FirstOrDefault();
            Log(req, Stage.Controller, "request_received", clientTs is not null ? $"client_ts={clientTs}" : null);
            ct.Register(() => Log(req, Stage.Kestrel, "disconnect_detected"));

            try
            {
                await chain.RunAsync(req, ct);
                Log(req, Stage.Controller, "response_sent");
                return Results.Ok();
            }
            catch (OperationCanceledException)
            {
                Log(req, Stage.Controller, "cancellation_propagated");
                return Results.Empty;
            }
        });

        app.MapGet("/stream-db", async (IStreamingDbService streaming, CancellationToken ct, HttpContext ctx) =>
        {
            var req = ctx.TraceIdentifier;
            var clientTs = ctx.Request.Query["ts"].FirstOrDefault();
            Log(req, Stage.Controller, "request_received", clientTs is not null ? $"client_ts={clientTs}" : null);
            ct.Register(() => Log(req, Stage.Kestrel, "disconnect_detected"));

            try
            {
                await streaming.RunAsync(req, ct);
                Log(req, Stage.Controller, "response_sent");
                return Results.Ok();
            }
            catch (OperationCanceledException)
            {
                Log(req, Stage.Controller, "cancellation_propagated");
                return Results.Empty;
            }
        });

        app.MapGet("/outbound", async (IHttpClientFactory factory, CancellationToken ct, HttpContext ctx) =>
        {
            var req = ctx.TraceIdentifier;
            var clientTs = ctx.Request.Query["ts"].FirstOrDefault();
            var downstreamUrl = Environment.GetEnvironmentVariable("DOWNSTREAM_URL")
                                ?? "http://downstream:8090";
            Log(req, Stage.Controller, "request_received", clientTs is not null ? $"client_ts={clientTs}" : null);
            ct.Register(() => Log(req, Stage.Kestrel, "disconnect_detected"));

            Log(req, Stage.AsyncOp, "outbound_started", $"url={downstreamUrl}/slow?delay=10");
            try
            {
                var client = factory.CreateClient();
                client.DefaultRequestHeaders.Add("X-Req-ID", req);
                await client.GetAsync($"{downstreamUrl}/slow?delay=10", ct);
                Log(req, Stage.AsyncOp, "outbound_completed");
                Log(req, Stage.Controller, "response_sent");
                return Results.Ok();
            }
            catch (OperationCanceledException)
            {
                Log(req, Stage.AsyncOp, "cancellation_detected", "source=outbound");
                Log(req, Stage.Controller, "cancellation_propagated");
                return Results.Empty;
            }
        });

        app.MapGet("/outbound-grpc", async (CancellationToken ct, HttpContext ctx) =>
        {
            var req = ctx.TraceIdentifier;
            var clientTs = ctx.Request.Query["ts"].FirstOrDefault();
            var grpcUrl = Environment.GetEnvironmentVariable("DOWNSTREAM_GRPC_URL")
                           ?? "http://downstream:50051";

            Log(req, Stage.Controller, "request_received", clientTs is not null ? $"client_ts={clientTs}" : null);
            ct.Register(() => Log(req, Stage.Kestrel, "disconnect_detected"));
            Log(req, Stage.AsyncOp, "outbound_grpc_started", $"url={grpcUrl}");

            try
            {
                using var channel = GrpcChannel.ForAddress(grpcUrl);
                var client = new DownstreamService.DownstreamServiceClient(channel);
                var request = new SlowRequest { ReqId = req, DelaySeconds = 10 };
                await client.SlowCallAsync(request, cancellationToken: ct);
                Log(req, Stage.AsyncOp, "outbound_grpc_completed");
                Log(req, Stage.Controller, "response_sent");
                return Results.Ok();
            }
            catch (Grpc.Core.RpcException rpc) when (rpc.StatusCode == Grpc.Core.StatusCode.Cancelled)
            {
                Log(req, Stage.AsyncOp, "cancellation_detected", "source=outbound_grpc");
                Log(req, Stage.Controller, "cancellation_propagated");
                return Results.Empty;
            }
            catch (OperationCanceledException)
            {
                Log(req, Stage.AsyncOp, "cancellation_detected", "source=outbound_grpc");
                Log(req, Stage.Controller, "cancellation_propagated");
                return Results.Empty;
            }
        });
    }
}
