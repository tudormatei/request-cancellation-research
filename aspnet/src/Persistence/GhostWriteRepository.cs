using Npgsql;
using static src.Observability.EventLog;

namespace src.Persistence;

public interface IGhostWriteRepository
{
    Task InsertAsync(string req, Guid reqId, int dMs, CancellationToken ct);

    Task CreateTableIfNotExistsAsync();
}

public class GhostWriteRepository(NpgsqlDataSource dataSource) : IGhostWriteRepository
{
    public async Task CreateTableIfNotExistsAsync()
    {
        await using var conn = await dataSource.OpenConnectionAsync();
        await using var cmd = new NpgsqlCommand(
            "CREATE TABLE IF NOT EXISTS ghost_writes (req_id UUID PRIMARY KEY, ts TIMESTAMPTZ NOT NULL DEFAULT NOW())",
            conn
        );
        await cmd.ExecuteNonQueryAsync();
    }

    public async Task InsertAsync(string req, Guid reqId, int dMs, CancellationToken ct)
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
        var dSeconds = dMs / 1000.0;
        Log(req, Stage.Db, "insert_started", $"D_ms={dMs}");

        await using var cmd = new NpgsqlCommand(
            "INSERT INTO ghost_writes(req_id, ts) SELECT @reqId, NOW() FROM pg_sleep(@dSeconds)",
            conn
        );
        cmd.Parameters.AddWithValue("reqId", reqId);
        cmd.Parameters.AddWithValue("dSeconds", dSeconds);

        try
        {
            await cmd.ExecuteNonQueryAsync(ct);
            Log(req, Stage.Db, "insert_completed");
        }
        catch (OperationCanceledException oce)
        {
            var detail = BuildExceptionDetail(oce);
            Log(req, Stage.Db, "cancellation_detected", $"phase=insert {detail}");
            throw;
        }
    }

    private static string BuildExceptionDetail(OperationCanceledException oce)
    {
        var inner = oce.InnerException;
        if (inner is Npgsql.PostgresException pgEx)
            return $"outer=OperationCanceledException inner=PostgresException sql_state={pgEx.SqlState}";
        if (inner is not null)
            return $"outer=OperationCanceledException inner={inner.GetType().Name} sql_state=None";
        return "outer=OperationCanceledException inner=None sql_state=None";
    }
}
