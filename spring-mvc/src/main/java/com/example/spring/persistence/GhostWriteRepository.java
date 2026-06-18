package com.example.spring.persistence;

import com.example.spring.cancellation.CancellationSource;
import com.example.spring.cancellation.CancelledException;
import com.example.spring.observability.EventLog;
import jakarta.annotation.PostConstruct;
import org.springframework.stereotype.Repository;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.sql.Statement;

public interface GhostWriteRepository {
    void insert(String req, String reqId, int dMs, CancellationSource source);
}

@Repository
class GhostWriteRepositoryImpl implements GhostWriteRepository {

    private final DataSource dataSource;

    GhostWriteRepositoryImpl(DataSource dataSource) {
        this.dataSource = dataSource;
    }

    @PostConstruct
    void createTableIfNotExists() {
        try (Connection conn = dataSource.getConnection();
             Statement stmt = conn.createStatement()) {
            stmt.execute(
                "CREATE TABLE IF NOT EXISTS ghost_writes " +
                "(req_id UUID PRIMARY KEY, ts TIMESTAMPTZ NOT NULL DEFAULT NOW())"
            );
        } catch (SQLException e) {
            throw new RuntimeException("Failed to create ghost_writes table", e);
        }
    }

    @Override
    public void insert(String req, String reqId, int dMs, CancellationSource source) {
        double dSeconds = dMs / 1000.0;
        EventLog.log(req, EventLog.Stage.DB, "insert_started", "D_ms=" + dMs);

        try (Connection conn = dataSource.getConnection();
             PreparedStatement pstmt = conn.prepareStatement(
                 "INSERT INTO ghost_writes(req_id, ts) " +
                 "SELECT ?::uuid, NOW() FROM pg_sleep(?)"
             )) {

            pstmt.setString(1, reqId);
            pstmt.setDouble(2, dSeconds);
            source.setActiveStatement(pstmt);

            try {
                pstmt.execute();
                EventLog.log(req, EventLog.Stage.DB, "insert_completed");
            } catch (SQLException e) {
                if (source.isCancelled() || "57014".equals(e.getSQLState())) {
                    EventLog.log(req, EventLog.Stage.DB, "cancellation_detected", "phase=insert");
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
