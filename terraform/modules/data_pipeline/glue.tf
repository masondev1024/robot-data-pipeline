resource "aws_glue_catalog_database" "main" {
  name = "robot_telemetry_db"
}

resource "aws_glue_catalog_table" "bronze" {
  name          = "bronze_robot_telemetry"
  database_name = aws_glue_catalog_database.main.name

  table_type = "EXTERNAL_TABLE"

  parameters = {
    "classification"            = "parquet"
    "projection.enabled"        = "true"
    "projection.year.type"      = "integer"
    "projection.year.range"     = "2024,2030"
    "projection.month.type"     = "integer"
    "projection.month.range"    = "1,12"
    "projection.month.digits"   = "2"
    "projection.day.type"       = "integer"
    "projection.day.range"      = "1,31"
    "projection.day.digits"     = "2"
    "projection.hour.type"      = "integer"
    "projection.hour.range"     = "0,23"
    "projection.hour.digits"    = "2"
    "storage.location.template" = "s3://${aws_s3_bucket.datalake.bucket}/bronze/year=$${year}/month=$${month}/day=$${day}/hour=$${hour}/"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.datalake.bucket}/bronze/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      name                  = "my-stream"
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"

      parameters = {
        "serialization.format" = "1"
      }
    }

    columns {
      name = "robot_id"
      type = "string"
    }
    columns {
      name = "pos_x"
      type = "double"
    }
    columns {
      name = "pos_y"
      type = "double"
    }
    columns {
      name = "battery_level"
      type = "double"
    }
    columns {
      name = "current_load"
      type = "double"
    }
    columns {
      name = "motor_temp"
      type = "double"
    }
    columns {
      name = "timestamp"
      type = "string"
    }
    columns {
      name = "failure_type"
      type = "string"
    }
  }

  partition_keys {
    name = "year"
    type = "string"
  }
  partition_keys {
    name = "month"
    type = "string"
  }
  partition_keys {
    name = "day"
    type = "string"
  }
  partition_keys {
    name = "hour"
    type = "string"
  }
}

resource "aws_glue_catalog_table" "silver_alerts" {
  name          = "silver_alerts"
  database_name = aws_glue_catalog_database.main.name

  table_type = "EXTERNAL_TABLE"

  parameters = {
    "classification"            = "parquet"
    "projection.enabled"        = "true"
    "projection.year.type"      = "integer"
    "projection.year.range"     = "2024,2030"
    "projection.month.type"     = "integer"
    "projection.month.range"    = "1,12"
    "projection.month.digits"   = "2"
    "projection.day.type"       = "integer"
    "projection.day.range"      = "1,31"
    "projection.day.digits"     = "2"
    "projection.hour.type"      = "integer"
    "projection.hour.range"     = "0,23"
    "projection.hour.digits"    = "2"
    "storage.location.template" = "s3://${aws_s3_bucket.datalake.bucket}/silver_alerts/year=$${year}/month=$${month}/day=$${day}/hour=$${hour}/"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.datalake.bucket}/silver_alerts/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      name                  = "silver-alerts-stream"
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"

      parameters = {
        "serialization.format" = "1"
      }
    }

    columns {
      name = "window_start"
      type = "string"
    }
    columns {
      name = "window_end"
      type = "string"
    }
    columns {
      name = "robot_id"
      type = "string"
    }
    columns {
      name = "avg_motor_temp"
      type = "double"
    }
    columns {
      name = "max_motor_temp"
      type = "double"
    }
    columns {
      name = "alert_count"
      type = "bigint"
    }
  }

  partition_keys {
    name = "year"
    type = "string"
  }
  partition_keys {
    name = "month"
    type = "string"
  }
  partition_keys {
    name = "day"
    type = "string"
  }
  partition_keys {
    name = "hour"
    type = "string"
  }
}

# Canonical batch Silver table. The schema matches sql/silver_ddl.sql and the
# robot_daily_etl Bronze -> Silver INSERT. Terraform owns the catalog contract;
# the SQL file remains a review/reference artifact and must not drift from this
# definition.
resource "aws_glue_catalog_table" "silver_robot_telemetry" {
  name          = "silver_robot_telemetry"
  database_name = aws_glue_catalog_database.main.name

  table_type = "EXTERNAL_TABLE"

  parameters = {
    "classification"              = "parquet"
    "parquet.compression"         = "SNAPPY"
    "projection.enabled"          = "true"
    "projection.dt.type"          = "date"
    "projection.dt.range"         = "2024-01-01,NOW"
    "projection.dt.format"        = "yyyy-MM-dd"
    "projection.dt.interval"      = "1"
    "projection.dt.interval.unit" = "DAYS"
    "storage.location.template"   = "s3://${aws_s3_bucket.datalake.bucket}/silver/dt=$${dt}/"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.datalake.bucket}/silver/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      name                  = "silver-robot-telemetry"
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"

      parameters = {
        "serialization.format" = "1"
      }
    }

    columns {
      name = "robot_id"
      type = "string"
    }
    columns {
      name = "pos_x"
      type = "double"
    }
    columns {
      name = "pos_y"
      type = "double"
    }
    columns {
      name = "battery_level"
      type = "int"
    }
    columns {
      name = "current_load"
      type = "int"
    }
    columns {
      name = "motor_temp"
      type = "double"
    }
    columns {
      name = "timestamp"
      type = "string"
    }
    columns {
      name = "failure_type"
      type = "string"
    }
  }

  partition_keys {
    name = "dt"
    type = "date"
  }
}

# Canonical batch Gold table. One row per robot/day is produced by the
# robot_daily_etl Silver -> Gold query and consumed by the API/PRISM layer.
resource "aws_glue_catalog_table" "gold_robot_daily_stats" {
  name          = "gold_robot_daily_stats"
  database_name = aws_glue_catalog_database.main.name

  table_type = "EXTERNAL_TABLE"

  parameters = {
    "classification"              = "parquet"
    "parquet.compression"         = "SNAPPY"
    "projection.enabled"          = "true"
    "projection.dt.type"          = "date"
    "projection.dt.range"         = "2024-01-01,NOW"
    "projection.dt.format"        = "yyyy-MM-dd"
    "projection.dt.interval"      = "1"
    "projection.dt.interval.unit" = "DAYS"
    "storage.location.template"   = "s3://${aws_s3_bucket.datalake.bucket}/gold/dt=$${dt}/"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.datalake.bucket}/gold/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      name                  = "gold-robot-daily-stats"
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"

      parameters = {
        "serialization.format" = "1"
      }
    }

    columns {
      name = "robot_id"
      type = "string"
    }
    columns {
      name = "avg_motor_temp"
      type = "double"
    }
    columns {
      name = "max_motor_temp"
      type = "double"
    }
    columns {
      name = "battery_start"
      type = "int"
    }
    columns {
      name = "battery_end"
      type = "int"
    }
    columns {
      name = "battery_drain"
      type = "int"
    }
    columns {
      name = "active_hours"
      type = "int"
    }
    columns {
      name = "anomaly_record_count"
      type = "int"
    }
    columns {
      name = "max_temp_load_ratio"
      type = "double"
    }
    columns {
      name = "dominant_failure_type"
      type = "string"
    }
  }

  partition_keys {
    name = "dt"
    type = "date"
  }
}

resource "aws_glue_registry" "main" {
  registry_name = "${var.project_name}-registry"
}

resource "aws_glue_schema" "telemetry" {
  schema_name  = "robot-telemetry-schema"
  registry_arn = aws_glue_registry.main.arn
  data_format  = "JSON"
  # Phase 8: failure_type 추가는 backward-compatible (default "NONE" + required 미포함).
  # 기존 v1 송신자도 v2 schema 로 검증 가능.
  compatibility = "BACKWARD"
  schema_definition = jsonencode({
    # description: 라이브 schema version v2 에 박혀있는 값과 일치 (Glue Schema 는 version
    # immutable 이라 description 제거 불가 → 코드에 명시 박아 영구 drift 해소).
    description = "v2 with failure_type"
    type        = "object"
    properties = {
      robot_id      = { type = "string" }
      pos_x         = { type = "number" }
      pos_y         = { type = "number" }
      battery_level = { type = "number" }
      current_load  = { type = "number" }
      motor_temp    = { type = "number" }
      timestamp     = { type = "string" }
      failure_type = {
        type    = "string"
        enum    = ["NONE", "TWF", "HDF", "PWF", "OSF", "RNF"]
        default = "NONE"
      }
    }
    required = ["robot_id", "timestamp"]
  })
}

# force_destroy: query history 가 남아있으면 DeleteWorkGroup 이 InvalidRequestException
# (workgroup is not empty) 로 막힘. terraform destroy 가 dependent EKS·VPC 까지 못 지움.
# 2026-05-23 사고 — 수동 `aws athena delete-work-group --recursive-delete-option` 으로 우회.
resource "aws_athena_workgroup" "main" {
  name          = "robot-telemetry-workgroup"
  force_destroy = true

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = var.athena_bytes_scanned_cutoff_per_query

    result_configuration {
      output_location = "s3://${aws_s3_bucket.datalake.bucket}/project-athena-results/"
    }
  }

  tags = {
    Project = var.project_name
  }
}
