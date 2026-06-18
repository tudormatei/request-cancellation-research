using Npgsql;
using static src.Observability.EventLog;

namespace src.Persistence;

public interface IWorkRepository
{
    Task SleepAsync(string req, int seconds, CancellationToken ct);
}

public class WorkRepository(NpgsqlDataSource dataSource) : IWorkRepository
{
    public async Task SleepAsync(string req, int seconds, CancellationToken ct)
    {
        NpgsqlConnection conn;
        try
        {
            conn = await dataSource.OpenConnectionAsync(ct);
        }
        catch (Exception) when (ct.IsCancellationRequested)
        {
            Log(req, Stage.Db, "cancellation_detected", "phase=connection");
            throw new OperationCanceledException(ct);
        }

        await using var _ = conn;
        Log(req, Stage.Db, "query_started", $"pg_sleep={seconds}s");

        try
        {
            await using var cmd = new NpgsqlCommand($"SELECT pg_sleep({seconds})", conn);
            await cmd.ExecuteNonQueryAsync(ct);
            Log(req, Stage.Db, "query_completed");
        }
        catch (Exception) when (ct.IsCancellationRequested)
        {
            Log(req, Stage.Db, "cancellation_detected", "phase=query");
            throw new OperationCanceledException(ct);
        }
    }
}
