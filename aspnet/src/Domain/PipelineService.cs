using System.Diagnostics;
using static src.Observability.EventLog;
using src.Persistence;

namespace src.Domain;

public interface IPipelineService
{
    Task RunAsync(string req, CancellationToken ct);
}

public class PipelineService(IWorkRepository repo) : IPipelineService
{
    private const int PreparationSeconds = 3;
    private const int YieldEveryIters = 100_000;

    public async Task RunAsync(string req, CancellationToken ct)
    {
        Log(req, Stage.Service, "stage_entered");

        var sw = Stopwatch.StartNew();
        long iters = 0;
        long primes = 0;
        long candidate = 2;

        try
        {
            while (sw.Elapsed.TotalSeconds < PreparationSeconds)
            {
                if (ct.IsCancellationRequested)
                {
                    Log(req, Stage.Service, "cancellation_detected",
                        $"phase=preparation iters={iters} primes={primes} elapsed_ms={sw.ElapsedMilliseconds}");
                    throw new OperationCanceledException(ct);
                }

                if (IsPrime(candidate)) primes++;
                candidate++;
                iters++;

                if (iters % YieldEveryIters == 0)
                    await Task.Yield();
            }
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        Log(req, Stage.Service, "preparation_completed",
            $"iters={iters} primes={primes} elapsed_ms={sw.ElapsedMilliseconds}");

        Log(req, Stage.AsyncOp, "started");
        try
        {
            await RunAsyncOperationAsync(req, ct);
        }
        catch (OperationCanceledException)
        {
            Log(req, Stage.AsyncOp, "cancellation_detected");
            throw;
        }
        Log(req, Stage.AsyncOp, "completed");

        await repo.SleepAsync(req, seconds: 5, ct);

        Log(req, Stage.Service, "stage_completed");
    }

    private static async Task RunAsyncOperationAsync(string req, CancellationToken ct)
    {
        await Task.Delay(3_000, ct);
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
