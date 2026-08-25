CREATE EXTERNAL TABLE IF NOT EXISTS robot_telemetry_db.bronze_robot_telemetry (
    robot_id      STRING,
    pos_x         DOUBLE,
    pos_y         DOUBLE,
    battery_level DOUBLE,
    current_load  DOUBLE,
    motor_temp    DOUBLE,
    `timestamp`   STRING,
    failure_type  STRING
)
-- Athena receives Firehose time-prefix partition values as strings. Keep this
-- contract aligned with Terraform/Glue and the Airflow predicates ('2026', ...).
PARTITIONED BY (year STRING, month STRING, day STRING, hour STRING)
STORED AS PARQUET
LOCATION 's3://__S3_BUCKET_NAME__/bronze/'
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
        's3://__S3_BUCKET_NAME__/bronze/year=${year}/month=${month}/day=${day}/hour=${hour}/'
);
