CREATE EXTERNAL TABLE IF NOT EXISTS robot_telemetry_db.gold_robot_daily_stats (
    robot_id               STRING,
    avg_motor_temp         DOUBLE,
    max_motor_temp         DOUBLE,
    battery_start          INT,
    battery_end            INT,
    battery_drain          INT,
    active_hours           INT,
    anomaly_record_count   INT,
    max_temp_load_ratio    DOUBLE,
    dominant_failure_type  STRING
)
PARTITIONED BY (dt DATE)
STORED AS PARQUET
LOCATION 's3://__S3_BUCKET_NAME__/gold/'
TBLPROPERTIES (
    'classification'              = 'parquet',
    'parquet.compression'         = 'SNAPPY',
    'projection.enabled'          = 'true',
    'projection.dt.type'          = 'date',
    'projection.dt.range'         = '2024-01-01,NOW',
    'projection.dt.format'        = 'yyyy-MM-dd',
    'projection.dt.interval'      = '1',
    'projection.dt.interval.unit' = 'DAYS',
    'storage.location.template'   =
        's3://__S3_BUCKET_NAME__/gold/dt=${dt}/'
);
