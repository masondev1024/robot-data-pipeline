data "aws_caller_identity" "current" {}

locals {
  common_tags = {
    Project     = var.project_name
    Environment = "validation"
    CostProfile = "pipeline-only"
    ManagedBy   = "terraform"
  }
}

resource "aws_s3_bucket" "datalake" {
  bucket        = var.s3_bucket_name
  force_destroy = true

  tags = local.common_tags
}

resource "aws_s3_bucket_public_access_block" "datalake" {
  bucket                  = aws_s3_bucket.datalake.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "datalake" {
  bucket = aws_s3_bucket.datalake.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "datalake" {
  bucket = aws_s3_bucket.datalake.id

  rule {
    id     = "expire-validation-evidence"
    status = "Enabled"

    filter {}

    expiration {
      days = var.validation_object_expiration_days
    }
  }
}

resource "aws_glue_catalog_database" "main" {
  name = "${var.project_name}-catalog"

  tags = local.common_tags
}

resource "aws_glue_catalog_table" "bronze" {
  name          = "bronze_robot_telemetry"
  database_name = aws_glue_catalog_database.main.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification            = "parquet"
    "projection.enabled"      = "true"
    "projection.year.type"    = "integer"
    "projection.year.range"   = "2024,2030"
    "projection.month.type"   = "integer"
    "projection.month.range"  = "1,12"
    "projection.month.digits" = "2"
    "projection.day.type"     = "integer"
    "projection.day.range"    = "1,31"
    "projection.day.digits"   = "2"
    "projection.hour.type"    = "integer"
    "projection.hour.range"   = "0,23"
    "projection.hour.digits"  = "2"
    "storage.location.template" = join("", [
      "s3://${aws_s3_bucket.datalake.bucket}/bronze/",
      "year=$${year}/month=$${month}/day=$${day}/hour=$${hour}/",
    ])
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.datalake.bucket}/bronze/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      name                  = "robot-telemetry-validation"
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

  depends_on = [aws_s3_bucket_server_side_encryption_configuration.datalake]
}

resource "aws_kinesis_stream" "main" {
  name             = "${var.project_name}-stream"
  shard_count      = var.kds_main_shard_count
  retention_period = var.kds_retention_period_hours

  tags = local.common_tags
}

data "aws_iam_policy_document" "firehose_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["firehose.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "firehose_delivery" {
  name               = "${var.project_name}-firehose-role"
  assume_role_policy = data.aws_iam_policy_document.firehose_assume_role.json

  tags = local.common_tags
}

data "aws_iam_policy_document" "firehose_delivery" {
  statement {
    sid    = "WriteValidationEvidence"
    effect = "Allow"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:GetBucketLocation",
      "s3:ListBucket",
      "s3:PutObject",
    ]
    resources = [
      aws_s3_bucket.datalake.arn,
      "${aws_s3_bucket.datalake.arn}/*",
    ]
  }

  statement {
    sid    = "ReadGlueSchema"
    effect = "Allow"
    actions = [
      "glue:GetTable",
      "glue:GetTableVersion",
      "glue:GetTableVersions",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "ReadKinesisSource"
    effect = "Allow"
    actions = [
      "kinesis:DescribeStream",
      "kinesis:GetRecords",
      "kinesis:GetShardIterator",
      "kinesis:ListShards",
    ]
    resources = [aws_kinesis_stream.main.arn]
  }
}

resource "aws_iam_role_policy" "firehose_delivery" {
  name   = "${var.project_name}-firehose-policy"
  role   = aws_iam_role.firehose_delivery.id
  policy = data.aws_iam_policy_document.firehose_delivery.json
}

resource "aws_kinesis_firehose_delivery_stream" "main" {
  name        = "${var.project_name}-firehose"
  destination = "extended_s3"

  lifecycle {
    precondition {
      condition     = !var.enable_parquet_conversion || var.firehose_buffering_size_mb >= 64
      error_message = "Firehose record format conversion requires firehose_buffering_size_mb >= 64. Disable Parquet conversion only when raw JSON validation is intentional."
    }
  }

  extended_s3_configuration {
    role_arn   = aws_iam_role.firehose_delivery.arn
    bucket_arn = aws_s3_bucket.datalake.arn

    prefix              = "bronze/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/hour=!{timestamp:HH}/"
    error_output_prefix = "bronze-dlq/!{firehose:error-output-type}/"
    buffering_size      = var.firehose_buffering_size_mb
    buffering_interval  = var.firehose_buffering_interval_seconds
    compression_format  = "UNCOMPRESSED"

    dynamic_partitioning_configuration {
      enabled = false
    }

    dynamic "data_format_conversion_configuration" {
      for_each = var.enable_parquet_conversion ? [true] : []

      content {
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
          role_arn      = aws_iam_role.firehose_delivery.arn
          region        = var.aws_region
        }
      }
    }

    s3_backup_mode = "Disabled"
  }

  kinesis_source_configuration {
    kinesis_stream_arn = aws_kinesis_stream.main.arn
    role_arn           = aws_iam_role.firehose_delivery.arn
  }

  tags = local.common_tags

  depends_on = [aws_iam_role_policy.firehose_delivery]
}

resource "aws_cloudwatch_metric_alarm" "iterator_age" {
  alarm_name          = "${var.project_name}-kds-iterator-age"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  datapoints_to_alarm = 2
  metric_name         = "GetRecords.IteratorAgeMilliseconds"
  namespace           = "AWS/Kinesis"
  period              = 60
  statistic           = "Maximum"
  threshold           = 120000
  treat_missing_data  = "notBreaching"
  alarm_description   = "Validation-only Kinesis consumer lag guardrail."
  actions_enabled     = false

  dimensions = {
    StreamName = aws_kinesis_stream.main.name
  }
}

resource "aws_cloudwatch_metric_alarm" "write_throttle" {
  alarm_name          = "${var.project_name}-kds-write-throttle"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  datapoints_to_alarm = 1
  metric_name         = "WriteProvisionedThroughputExceeded"
  namespace           = "AWS/Kinesis"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_description   = "Validation-only Kinesis write throttle guardrail."
  actions_enabled     = false

  dimensions = {
    StreamName = aws_kinesis_stream.main.name
  }
}

resource "aws_cloudwatch_metric_alarm" "firehose_freshness" {
  alarm_name          = "${var.project_name}-firehose-freshness"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  metric_name         = "DeliveryToS3.DataFreshness"
  namespace           = "AWS/Firehose"
  period              = 60
  statistic           = "Maximum"
  threshold           = var.firehose_freshness_threshold_seconds
  treat_missing_data  = "notBreaching"
  alarm_description   = "Validation-only Firehose delivery freshness guardrail."
  actions_enabled     = false

  dimensions = {
    DeliveryStreamName = aws_kinesis_firehose_delivery_stream.main.name
  }
}

resource "aws_cloudwatch_metric_alarm" "firehose_success" {
  alarm_name          = "${var.project_name}-firehose-success"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  metric_name         = "DeliveryToS3.Success"
  namespace           = "AWS/Firehose"
  period              = 60
  statistic           = "Minimum"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  alarm_description   = "Validation-only Firehose successful S3 put count guardrail."
  actions_enabled     = false

  dimensions = {
    DeliveryStreamName = aws_kinesis_firehose_delivery_stream.main.name
  }
}
