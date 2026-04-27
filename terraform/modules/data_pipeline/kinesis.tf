# Kinesis Data Streams
resource "aws_kinesis_stream" "main" {
  name             = "${var.project_name}-stream"
  shard_count      = 10
  retention_period = 24

  tags = {
    Name = "${var.project_name}-stream"
  }
}

resource "aws_kinesis_stream" "alert" {
  name             = "robot-anomaly-alert-stream"
  shard_count      = 2
  retention_period = 24

  tags = {
    Name = "robot-anomaly-alert-stream"
  }
}

# Kinesis Data Firehose
resource "aws_kinesis_firehose_delivery_stream" "main" {
  name        = "${var.project_name}-firehose"
  destination = "extended_s3"

  extended_s3_configuration {
    role_arn   = aws_iam_role.firehose_delivery_role.arn
    bucket_arn = aws_s3_bucket.datalake.arn

    prefix              = "bronze/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/hour=!{timestamp:HH}/"
    error_output_prefix = "bronze-dlq/!{firehose:error-output-type}/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/hour=!{timestamp:HH}/"

    buffer_size        = 64 # 최소값 (format conversion 필수)
    buffer_interval    = 60 # 테스트용: 1분마다 플러시
    compression_format = "UNCOMPRESSED"

    dynamic_partitioning_configuration {
      enabled = true
    }

    data_format_conversion_configuration {
      input_format_configuration {
        deserializer {
          open_x_json_ser_de {}
        }
      }

      output_format_configuration {
        serializer {
          parquet_ser_de {
            compression = "SNAPPY"
          }
        }
      }

      schema_configuration {
        database_name = aws_glue_catalog_database.main.name
        table_name    = aws_glue_catalog_table.bronze.name
        role_arn      = aws_iam_role.firehose_delivery_role.arn
      }
    }

    s3_backup_mode = "Enabled"
  }

  kinesis_source_configuration {
    kinesis_stream_arn = aws_kinesis_stream.main.arn
    role_arn           = aws_iam_role.firehose_delivery_role.arn
  }
}
