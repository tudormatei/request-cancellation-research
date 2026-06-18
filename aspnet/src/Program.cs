using Npgsql;
using src.Domain;
using src.Persistence;
using src.Presentation;

var builder = WebApplication.CreateBuilder(args);

builder.Logging.ClearProviders();

var connStr = builder.Configuration.GetConnectionString("DefaultConnection")!;
builder.Services.AddSingleton(NpgsqlDataSource.Create(connStr));
builder.Services.AddScoped<IWorkRepository, WorkRepository>();

builder.Services.AddScoped<ICpuService, CpuService>();
builder.Services.AddScoped<IDbService, DbService>();
builder.Services.AddScoped<IPipelineService, PipelineService>();
builder.Services.AddScoped<IChainedService, ChainedService>();
builder.Services.AddScoped<IStreamingWorkRepository, StreamingWorkRepository>();
builder.Services.AddScoped<IStreamingDbService, StreamingDbService>();
builder.Services.AddScoped<IGhostWriteRepository, GhostWriteRepository>();
builder.Services.AddScoped<ITwoStepWriteRepository, TwoStepWriteRepository>();
builder.Services.AddHttpClient();

if (int.TryParse(Environment.GetEnvironmentVariable("THREAD_POOL_MAX"), out var tmax))
    ThreadPool.SetMaxThreads(tmax, tmax);

if (int.TryParse(Environment.GetEnvironmentVariable("THREAD_POOL_MIN"), out var tmin))
    ThreadPool.SetMinThreads(tmin, tmin);

var app = builder.Build();

app.MapWorkEndpoints();

var dataSource = app.Services.GetRequiredService<NpgsqlDataSource>();
app.Lifetime.ApplicationStarted.Register(() =>
{
    ThreadPool.GetMinThreads(out int minWorker, out _);
    ThreadPool.GetMaxThreads(out int maxWorker, out _);
    Console.WriteLine($"threadpool min_worker={minWorker} max_worker={maxWorker} logical_cpus={Environment.ProcessorCount}");
    Console.WriteLine($"yield_interval_ms={src.Domain.CpuService.YieldIntervalMs}");
    Console.WriteLine($"cpu_duration_s={src.Domain.CpuService.DurationSeconds}");

    try
    {
        using var conn = dataSource.OpenConnection();
        using var cmd = conn.CreateCommand();
        cmd.CommandText = "CREATE TABLE IF NOT EXISTS ghost_writes (req_id UUID PRIMARY KEY, ts TIMESTAMPTZ NOT NULL DEFAULT NOW())";
        cmd.ExecuteNonQuery();
        cmd.CommandText = "CREATE TABLE IF NOT EXISTS txn_writes (req_id UUID NOT NULL, step INT NOT NULL, ts TIMESTAMPTZ NOT NULL DEFAULT NOW(), PRIMARY KEY(req_id, step))";
        cmd.ExecuteNonQuery();
        Console.WriteLine("aspnet ready");
    }
    catch (Exception ex)
    {
        Console.Error.WriteLine($"aspnet warmup failed: {ex.Message} (connStr={connStr})");
    }
});

app.Run();
