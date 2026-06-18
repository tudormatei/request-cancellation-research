namespace src.Observability;

public static class EventLog
{
    public static class Stage
    {
        public const string Kestrel = "kestrel";
        public const string Controller = "controller";
        public const string Service = "service";
        public const string AsyncOp = "async_op";
        public const string Db = "db";
    }

    public static void Log(string req, string stage, string @event, string? detail = null)
    {
        var ts = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        var line = detail is null
            ? $"ts={ts} req={req} stage={stage} event={@event}"
            : $"ts={ts} req={req} stage={stage} event={@event} detail={detail}";
        Console.WriteLine(line);
    }
}
