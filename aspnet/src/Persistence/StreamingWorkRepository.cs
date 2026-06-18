using Npgsql;
using static src.Observability.EventLog;

namespace src.Persistence;

public interface IStreamingWorkRepository
{
    Task StreamAsync(string req, CancellationToken ct);
}

public class StreamingWorkRepository(NpgsqlDataSource dataSource) : IStreamingWorkRepository
{
    public async Task StreamAsync(string req, CancellationToken ct)
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
        Log(req, Stage.Db, "stream_started");

        try
        {
            await using var cmd = new NpgsqlCommand(
                "SELECT n, pg_sleep(0.0001) FROM generate_series(1, 30000) AS n", conn);
            await using var reader = await cmd.ExecuteReaderAsync(ct);

            int count = 0;
            while (await reader.ReadAsync(ct))
            {
                count++;
                if (count % 1_000 == 0)
                    Log(req, Stage.Db, "rows_consumed", $"count={count}");
            }

            Log(req, Stage.Db, "stream_completed", $"total={count}");
        }
        catch (Exception) when (ct.IsCancellationRequested)
        {
            Log(req, Stage.Db, "cancellation_detected", "phase=stream");
            throw new OperationCanceledException(ct);
        }
    }
}
