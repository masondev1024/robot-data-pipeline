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
    'parquet.compress' = 'SNAPPY'
);
