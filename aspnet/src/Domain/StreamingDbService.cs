using static src.Observability.EventLog;
using src.Persistence;

namespace src.Domain;

public interface IStreamingDbService
{
    Task RunAsync(string req, CancellationToken ct);
}

public class StreamingDbService(IStreamingWorkRepository repo) : IStreamingDbService
{
    public async Task RunAsync(string req, CancellationToken ct)
    {
        Log(req, Stage.Service, "stage_entered");
        try
        {
            await repo.StreamAsync(req, ct);
            Log(req, Stage.Service, "stage_completed");
        }
        catch (OperationCanceledException)
        {
            Log(req, Stage.Service, "cancellation_detected");
            throw;
        }
    }
}
