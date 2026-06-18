using System.Diagnostics;
using static src.Observability.EventLog;

namespace src.Domain;

public interface ICpuService
{
    Task RunAsync(string req, CancellationToken ct);
}

public class CpuService : ICpuService
{
    internal static readonly int DurationSeconds =
        int.TryParse(Environment.GetEnvironmentVariable("CPU_DURATION_S"), out var d) ? d : 15;
    internal static readonly long YieldIntervalMs =
        long.TryParse(Environment.GetEnvironmentVariable("YIELD_INTERVAL_MS"), out var v) ? v : 100;

    public async Task RunAsync(string req, CancellationToken ct)
    {
        Log(req, Stage.Service, "stage_entered");

        var sw = Stopwatch.StartNew();
        long iters = 0;
        long primes = 0;
        long candidate = 2;
        long lastYieldMs = 0;

        Log(req, Stage.Service, "work_started");

        while (sw.Elapsed.TotalSeconds < DurationSeconds)
        {
            if (ct.IsCancellationRequested)
            {
                Log(req, Stage.Service, "cancellation_detected",
                    $"iters={iters} primes={primes} elapsed_ms={sw.ElapsedMilliseconds}");
                throw new OperationCanceledException(ct);
            }

            if (IsPrime(candidate)) primes++;
            candidate++;
            iters++;

            if (sw.ElapsedMilliseconds - lastYieldMs >= YieldIntervalMs)
            {
                lastYieldMs = sw.ElapsedMilliseconds;
                await Task.Yield();
            }
        }

        Log(req, Stage.Service, "work_completed",
            $"iters={iters} primes={primes} elapsed_ms={sw.ElapsedMilliseconds}");
    }

    private static bool IsPrime(long n)
    {
        if (n < 2) return false;
        if (n == 2) return true;
        if (n % 2 == 0) return false;
        for (long i = 3; i * i <= n; i += 2)
            if (n % i == 0) return false;
        return true;
    }
}
