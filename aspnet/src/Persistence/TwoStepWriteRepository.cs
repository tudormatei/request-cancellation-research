using Npgsql;
using static src.Observability.EventLog;

namespace src.Persistence;

public interface ITwoStepWriteRepository
{
    Task WriteTwoStepsAsync(string req, Guid reqId, int gapMs, bool txnMode, CancellationToken ct);
}

public class TwoStepWriteRepository(NpgsqlDataSource dataSource) : ITwoStepWriteRepository
{
    public async Task WriteTwoStepsAsync(string req, Guid reqId, int gapMs, bool txnMode, CancellationToken ct)
    {
        await using var conn = await dataSource.OpenConnectionAsync(ct);

        if (txnMode)
        {
            await using var txn = await conn.BeginTransactionAsync(ct);
            await InsertStep(conn, txn, reqId, 1, req, ct);
            Log(req, Stage.Db, "gap_started", $"gap_ms={gapMs} tx=true");
            await Task.Delay(gapMs, ct);
            Log(req, Stage.Db, "gap_completed");
            await InsertStep(conn, txn, reqId, 2, req, ct);
            await txn.CommitAsync(ct);
            Log(req, Stage.Db, "txn_committed");
        }
        else
        {
            await InsertStep(conn, null, reqId, 1, req, ct);
            Log(req, Stage.Db, "gap_started", $"gap_ms={gapMs} tx=false");
            await Task.Delay(gapMs, ct);
            Log(req, Stage.Db, "gap_completed");
            await InsertStep(conn, null, reqId, 2, req, ct);
        }
    }

    private static async Task InsertStep(NpgsqlConnection conn, NpgsqlTransaction? txn,
                                         Guid reqId, int step, string req, CancellationToken ct)
    {
        Log(req, Stage.Db, "insert_started", $"step={step}");
        await using var cmd = new NpgsqlCommand(
            $"INSERT INTO txn_writes(req_id, step) VALUES(@reqId, @step) /* req={reqId} */", conn, txn);
        cmd.Parameters.AddWithValue("reqId", reqId);
        cmd.Parameters.AddWithValue("step", step);
        await cmd.ExecuteNonQueryAsync(ct);
        Log(req, Stage.Db, "insert_completed", $"step={step}");
    }
}
