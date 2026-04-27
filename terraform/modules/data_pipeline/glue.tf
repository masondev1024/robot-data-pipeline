resource "aws_glue_catalog_database" "main" {
  name = "robot_telemetry_db"
}

resource "aws_glue_catalog_table" "bronze" {
  name          = "bronze_robot_telemetry"
  database_name = aws_glue_catalog_database.main.name

  table_type = "EXTERNAL_TABLE"

  parameters = {
    "classification" = "parquet"
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

resource "aws_glue_registry" "main" {
  registry_name = "${var.project_name}-registry"
}

resource "aws_glue_schema" "telemetry" {
  schema_name   = "robot-telemetry-schema"
  registry_arn  = aws_glue_registry.main.arn
  data_format   = "JSON"
  compatibility = "BACKWARD"
  schema_definition = jsonencode({
    type = "object"
    properties = {
      robot_id      = { type = "string" }
      pos_x         = { type = "number" }
      pos_y         = { type = "number" }
      battery_level = { type = "number" }
      current_load  = { type = "number" }
      motor_temp    = { type = "number" }
      timestamp     = { type = "string" }
    }
    required = ["robot_id", "timestamp"]
  })
}

resource "aws_athena_workgroup" "main" {
  name = "robot-telemetry-workgroup"

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true

    result_configuration {
      output_location = "s3://${aws_s3_bucket.datalake.bucket}/project-athena-results/"
    }
  }

  tags = {
    Project = var.project_name
  }
}
