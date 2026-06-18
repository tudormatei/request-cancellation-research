using static src.Observability.EventLog;
using src.Persistence;

namespace src.Domain;

public interface IDbService
{
    Task RunAsync(string req, CancellationToken ct);
}

public class DbService(IWorkRepository repo) : IDbService
{
    public async Task RunAsync(string req, CancellationToken ct)
    {
        Log(req, Stage.Service, "stage_entered");

        try
        {
            await repo.SleepAsync(req, seconds: 10, ct);
            Log(req, Stage.Service, "stage_completed");
        }
        catch (OperationCanceledException)
        {
            Log(req, Stage.Service, "cancellation_detected");
            throw;
        }
    }
}
