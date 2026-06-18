package com.example.spring.cancellation;

import java.sql.SQLException;
import java.sql.Statement;
import java.util.concurrent.atomic.AtomicBoolean;

public class CancellationSource {

    private final AtomicBoolean cancelled = new AtomicBoolean(false);

    private volatile Thread workerThread;
    private volatile Statement activeStatement;

    public void setWorkerThread(Thread t) { this.workerThread = t; }
    public void setActiveStatement(Statement s) { this.activeStatement = s; }
    public void clearActiveStatement() { this.activeStatement = null; }

    public boolean isCancelled() { return cancelled.get(); }

    public void cancel() {
        if (!cancelled.compareAndSet(false, true)) return;

        Thread t = workerThread;
        if (t != null) t.interrupt();

        Statement s = activeStatement;
        if (s != null) {
            try { s.cancel(); } catch (SQLException ignored) {}
        }
    }
}
