CREATE EXTERNAL TABLE IF NOT EXISTS robot_telemetry_db.silver_robot_telemetry (
    robot_id      STRING,
    pos_x         DOUBLE,
    pos_y         DOUBLE,
    battery_level INT,
    current_load  INT,
    motor_temp    DOUBLE,
    `timestamp`   STRING,
    failure_type  STRING
)
PARTITIONED BY (dt DATE)
STORED AS PARQUET
LOCATION 's3://__S3_BUCKET_NAME__/silver/'
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
        's3://__S3_BUCKET_NAME__/silver/dt=${dt}/'
);
