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

public interface TwoStepWriteRepository {
    void writeTwoSteps(String req, String reqId, int gapMs, boolean txnMode, CancellationSource source);
}

@Repository
class TwoStepWriteRepositoryImpl implements TwoStepWriteRepository {

    private final DataSource dataSource;

    TwoStepWriteRepositoryImpl(DataSource dataSource) {
        this.dataSource = dataSource;
    }

    @PostConstruct
    void createTableIfNotExists() {
        try (Connection conn = dataSource.getConnection();
             Statement stmt = conn.createStatement()) {
            stmt.execute("CREATE TABLE IF NOT EXISTS txn_writes " +
                "(req_id UUID NOT NULL, step INT NOT NULL, ts TIMESTAMPTZ NOT NULL DEFAULT NOW(), " +
                "PRIMARY KEY(req_id, step))");
        } catch (SQLException e) {
            throw new RuntimeException("Failed to create txn_writes table", e);
        }
    }

    @Override
    public void writeTwoSteps(String req, String reqId, int gapMs, boolean txnMode, CancellationSource source) {
        EventLog.log(req, EventLog.Stage.DB, "two_step_started", "gap_ms=" + gapMs + " tx=" + txnMode);
        try (Connection conn = dataSource.getConnection()) {
            if (txnMode) conn.setAutoCommit(false);
            try {
                insertStep(conn, reqId, 1, req, source);

                EventLog.log(req, EventLog.Stage.DB, "gap_started", "gap_ms=" + gapMs);
                try {
                    Thread.sleep(gapMs);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    EventLog.log(req, EventLog.Stage.DB, "cancellation_detected", "phase=gap");
                    if (txnMode) conn.rollback();
                    throw new CancelledException();
                }
                EventLog.log(req, EventLog.Stage.DB, "gap_completed");

                insertStep(conn, reqId, 2, req, source);

                if (txnMode) {
                    conn.commit();
                    EventLog.log(req, EventLog.Stage.DB, "txn_committed");
                }
            } catch (SQLException e) {
                if (txnMode) { try { conn.rollback(); } catch (SQLException ignore) {} }
                if (source.isCancelled() || "57014".equals(e.getSQLState())) {
                    EventLog.log(req, EventLog.Stage.DB, "cancellation_detected", "phase=insert");
                    throw new CancelledException();
                }
                throw new RuntimeException(e);
            }
        } catch (SQLException e) {
            throw new RuntimeException(e);
        }
    }

    private void insertStep(Connection conn, String reqId, int step, String req, CancellationSource source)
            throws SQLException {
        EventLog.log(req, EventLog.Stage.DB, "insert_started", "step=" + step);
        try (PreparedStatement pstmt = conn.prepareStatement(
                "INSERT INTO txn_writes(req_id, step) VALUES (?::uuid, ?) /* req=" + reqId + " */")) {
            pstmt.setString(1, reqId);
            pstmt.setInt(2, step);
            source.setActiveStatement(pstmt);
            try {
                pstmt.execute();
                EventLog.log(req, EventLog.Stage.DB, "insert_completed", "step=" + step);
            } finally {
                source.clearActiveStatement();
            }
        }
    }
}
