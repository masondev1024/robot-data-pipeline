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

    # 학습 환경 비용 최적화 — Bronze 신선도 5분/15분 trade-off (2026-05-04 drift sync)
    buffering_size     = var.firehose_buffering_size_mb
    buffering_interval = var.firehose_buffering_interval_seconds
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

  # IAM 정책 전파 지연(eventual consistency) 대응
  depends_on = [aws_iam_role_policy.firehose_delivery]
}

# Silver Alerts Firehose — Flink anomaly alert stream → S3 Parquet 영구 보관
# (Bedrock RAG / 사후 패턴 분석 / weekly_dq_report false-positive 추적용)
resource "aws_kinesis_firehose_delivery_stream" "alert_archive" {
  name        = "robot-anomaly-alert-archive-firehose"
  destination = "extended_s3"

  extended_s3_configuration {
    role_arn   = aws_iam_role.firehose_delivery_role.arn
    bucket_arn = aws_s3_bucket.datalake.arn

    prefix              = "silver_alerts/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/hour=!{timestamp:HH}/"
    error_output_prefix = "silver_alerts-dlq/!{firehose:error-output-type}/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/hour=!{timestamp:HH}/"

    # 학습 환경 비용 최적화 — Bronze 신선도 5분/15분 trade-off (2026-05-04 drift sync)
    # alert 빈도 낮음 → 큰 buffer 로 S3 PUT 비용 ↓ (Parquet 압축 효율 ↑)
    buffering_size     = var.alert_firehose_buffering_size_mb
    buffering_interval = var.alert_firehose_buffering_interval_seconds
    compression_format = "UNCOMPRESSED"

    # bronze Firehose 와 동일: timestamp 네임스페이스만 사용
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
        table_name    = aws_glue_catalog_table.silver_alerts.name
        role_arn      = aws_iam_role.firehose_delivery_role.arn
      }
    }

    s3_backup_mode = "Disabled"
  }

  kinesis_source_configuration {
    kinesis_stream_arn = aws_kinesis_stream.alert.arn
    role_arn           = aws_iam_role.firehose_delivery_role.arn
  }

  tags = {
    Name  = "robot-anomaly-alert-archive-firehose"
    Owner = "de-ai-06" # AWS 실측 정합 (2026-05-04 drift sync)
  }

  depends_on = [aws_iam_role_policy.firehose_delivery]
}
