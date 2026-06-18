using static src.Observability.EventLog;
using src.Persistence;

namespace src.Domain;

public interface IChainedService
{
    Task RunAsync(string req, CancellationToken ct);
}

public class ChainedService(IWorkRepository repo) : IChainedService
{
    public async Task RunAsync(string req, CancellationToken ct)
    {
        Log(req, Stage.Service, "stage_entered");

        Log(req, Stage.AsyncOp, "task_a_started");
        try
        {
            await Task.Delay(3_000, ct);
        }
        catch (OperationCanceledException)
        {
            Log(req, Stage.AsyncOp, "cancellation_detected", "task=a");
            throw;
        }
        Log(req, Stage.AsyncOp, "task_a_completed");

        Log(req, Stage.AsyncOp, "task_b_started");
        try
        {
            await Task.Delay(3_000, ct);
        }
        catch (OperationCanceledException)
        {
            Log(req, Stage.AsyncOp, "cancellation_detected", "task=b");
            throw;
        }
        Log(req, Stage.AsyncOp, "task_b_completed");

        Log(req, Stage.AsyncOp, "task_c_started");
        try
        {
            await repo.SleepAsync(req, seconds: 5, ct);
        }
        catch (OperationCanceledException)
        {
            Log(req, Stage.AsyncOp, "cancellation_detected", "task=c");
            throw;
        }
        Log(req, Stage.AsyncOp, "task_c_completed");

        Log(req, Stage.Service, "stage_completed");
    }
}
