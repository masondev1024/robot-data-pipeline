CREATE EXTERNAL TABLE IF NOT EXISTS robot_telemetry_db.gold_robot_daily_stats (
    robot_id       STRING,
    avg_motor_temp DOUBLE,
    max_motor_temp DOUBLE,
    battery_start  INT,
    battery_end    INT,
    battery_drain  INT,
    active_hours   INT
)
PARTITIONED BY (dt DATE)
STORED AS PARQUET
LOCATION 's3://de-ai-06-827913617635-ap-northeast-2-an/gold/'
TBLPROPERTIES (
    'parquet.compression'         = 'SNAPPY',
    'projection.enabled'          = 'true',
    'projection.dt.type'          = 'date',
    'projection.dt.range'         = '2024-01-01,NOW',
    'projection.dt.format'        = 'yyyy-MM-dd',
    'projection.dt.interval'      = '1',
    'projection.dt.interval.unit' = 'DAYS',
    'storage.location.template'   =
        's3://de-ai-06-827913617635-ap-northeast-2-an/gold/dt=${dt}/'
);
