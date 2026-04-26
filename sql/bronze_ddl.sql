CREATE EXTERNAL TABLE IF NOT EXISTS robot_telemetry_db.bronze_robot_telemetry (
    robot_id      STRING,
    pos_x         DOUBLE,
    pos_y         DOUBLE,
    battery_level INT,
    current_load  INT,
    motor_temp    DOUBLE,
    `timestamp`   STRING
)
PARTITIONED BY (year INT, month INT, day INT, hour INT)
STORED AS PARQUET
LOCATION 's3://de-ai-06-827913617635-ap-northeast-2-an/bronze/'
TBLPROPERTIES (
    'projection.enabled'        = 'true',
    'projection.year.type'      = 'integer',
    'projection.year.range'     = '2024,2030',
    'projection.month.type'     = 'integer',
    'projection.month.range'    = '1,12',
    'projection.month.digits'   = '2',
    'projection.day.type'       = 'integer',
    'projection.day.range'      = '1,31',
    'projection.day.digits'     = '2',
    'projection.hour.type'      = 'integer',
    'projection.hour.range'     = '0,23',
    'projection.hour.digits'    = '2',
    'storage.location.template' =
        's3://de-ai-06-827913617635-ap-northeast-2-an/bronze/year=${year}/month=${month}/day=${day}/hour=${hour}/'
);
