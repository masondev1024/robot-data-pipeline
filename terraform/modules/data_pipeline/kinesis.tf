# Kinesis Data Streams
resource "aws_kinesis_stream" "main" {
  name             = "${var.project_name}-stream"
  shard_count      = var.kds_main_shard_count
  retention_period = 24

  tags = {
    Name = "${var.project_name}-stream"
  }
}

resource "aws_kinesis_stream" "alert" {
  name             = "robot-anomaly-alert-stream"
  shard_count      = var.kds_alert_shard_count
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

    buffering_size     = 64 # 최소값 (Parquet format conversion 필수)
    buffering_interval = 60 # 테스트용: 1분마다 플러시 (시연 사각지대 최소화)
    compression_format = "UNCOMPRESSED"

    # 시연용: timestamp 네임스페이스만 사용하므로 dynamic partitioning 비활성화.
    # `!{timestamp:...}` 파티셔닝은 dynamic partitioning과 무관하게 동작함.
    # (활성화하려면 processing_configuration의 JQ MetadataExtraction processor 필요)
    dynamic_partitioning_configuration {
      enabled = false
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

    # 시연용: 별도 백업 불필요. "Enabled" 시 s3_backup_configuration 블록 필수.
    s3_backup_mode = "Disabled"
  }

  kinesis_source_configuration {
    kinesis_stream_arn = aws_kinesis_stream.main.arn
    role_arn           = aws_iam_role.firehose_delivery_role.arn
  }
}
