package com.example.webflux.observability;

public final class EventLog {

    public static final class Stage {
        public static final String NETTY = "netty";
        public static final String CONTROLLER = "controller";
        public static final String SERVICE = "service";
        public static final String ASYNC_OP = "async_op";
        public static final String DB = "db";

        private Stage() {}
    }

    public static void log(String req, String stage, String event) {
        log(req, stage, event, null);
    }

    public static void log(String req, String stage, String event, String detail) {
        long ts = System.currentTimeMillis();
        String line = detail == null
                ? "ts=" + ts + " req=" + req + " stage=" + stage + " event=" + event
                : "ts=" + ts + " req=" + req + " stage=" + stage + " event=" + event + " detail=" + detail;
        System.out.println(line);
    }

    private EventLog() {}
}
