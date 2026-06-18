package com.example.spring.persistence;

import com.example.spring.cancellation.CancellationSource;
import com.example.spring.cancellation.CancelledException;
import com.example.spring.observability.EventLog;
import org.springframework.stereotype.Repository;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.SQLException;
import java.sql.Statement;

public interface WorkRepository {
    void sleep(String req, int seconds, CancellationSource source);
}

@Repository
class WorkRepositoryImpl implements WorkRepository {

    private final DataSource dataSource;

    WorkRepositoryImpl(DataSource dataSource) {
        this.dataSource = dataSource;
    }

    @Override
    public void sleep(String req, int seconds, CancellationSource source) {
        EventLog.log(req, EventLog.Stage.DB, "query_started", "pg_sleep=" + seconds + "s");

        try (Connection conn = dataSource.getConnection();
             Statement stmt = conn.createStatement()) {

            source.setActiveStatement(stmt);

            try {
                stmt.execute("SELECT pg_sleep(" + seconds + ")");
                EventLog.log(req, EventLog.Stage.DB, "query_completed");
            } catch (SQLException e) {
                if (source.isCancelled() || "57014".equals(e.getSQLState())) {
                    EventLog.log(req, EventLog.Stage.DB, "cancellation_detected", "phase=query");
                    throw new CancelledException();
                }
                throw new RuntimeException(e);
            } finally {
                source.clearActiveStatement();
            }

        } catch (SQLException e) {
            if (source.isCancelled()) {
                EventLog.log(req, EventLog.Stage.DB, "cancellation_detected", "phase=connection");
                throw new CancelledException();
            }
            throw new RuntimeException(e);
        }
    }
}
