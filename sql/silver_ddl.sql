CREATE EXTERNAL TABLE IF NOT EXISTS robot_telemetry_db.silver_robot_telemetry (
    robot_id      STRING,
    pos_x         DOUBLE,
    pos_y         DOUBLE,
    battery_level INT,
    current_load  INT,
    motor_temp    DOUBLE,
    `timestamp`   STRING
)
PARTITIONED BY (dt DATE)
STORED AS PARQUET
LOCATION 's3://de-ai-06-827913617635-ap-northeast-2-an/silver/'
TBLPROPERTIES (
    'parquet.compress' = 'SNAPPY'
);
