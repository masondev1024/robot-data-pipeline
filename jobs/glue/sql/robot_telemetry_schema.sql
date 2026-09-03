-- MySQL 8 schema for the short-lived Glue migration lab.
-- Staging is append-only per attempt; target is idempotent by event_id.

CREATE TABLE IF NOT EXISTS robot_telemetry_migration_audit (
    batch_id VARCHAR(128) NOT NULL,
    attempt_id VARCHAR(128) NOT NULL,
    source_path TEXT NOT NULL,
    source_rows BIGINT NOT NULL,
    accepted_rows BIGINT NOT NULL,
    rejected_rows BIGINT NOT NULL,
    staged_rows BIGINT NOT NULL DEFAULT 0,
    merged_rows BIGINT NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL,
    error_message VARCHAR(1000) NULL,
    started_at TIMESTAMP(6) NOT NULL,
    completed_at TIMESTAMP(6) NULL,
    PRIMARY KEY (batch_id, attempt_id)
);

CREATE TABLE IF NOT EXISTS robot_telemetry_migration_stg (
    event_id CHAR(64) NOT NULL,
    batch_id VARCHAR(128) NOT NULL,
    attempt_id VARCHAR(128) NOT NULL,
    robot_id VARCHAR(128) NOT NULL,
    pos_x DOUBLE NOT NULL,
    pos_y DOUBLE NOT NULL,
    battery_level DOUBLE NOT NULL,
    current_load DOUBLE NOT NULL,
    motor_temp DOUBLE NOT NULL,
    source_event_time TIMESTAMP(6) NOT NULL,
    failure_type VARCHAR(8) NOT NULL,
    source_path TEXT NOT NULL,
    ingested_at TIMESTAMP(6) NOT NULL,
    KEY idx_migration_stg_batch (batch_id, attempt_id),
    KEY idx_migration_stg_event (event_id)
);

CREATE TABLE IF NOT EXISTS robot_telemetry (
    event_id CHAR(64) NOT NULL,
    robot_id VARCHAR(128) NOT NULL,
    pos_x DOUBLE NOT NULL,
    pos_y DOUBLE NOT NULL,
    battery_level DOUBLE NOT NULL,
    current_load DOUBLE NOT NULL,
    motor_temp DOUBLE NOT NULL,
    event_time TIMESTAMP(6) NOT NULL,
    failure_type VARCHAR(8) NOT NULL,
    batch_id VARCHAR(128) NOT NULL,
    source_path TEXT NOT NULL,
    ingested_at TIMESTAMP(6) NOT NULL,
    PRIMARY KEY (event_id),
    UNIQUE KEY uq_robot_event_time (robot_id, event_time),
    KEY idx_robot_event_time (event_time),
    KEY idx_failure_type (failure_type)
);
