# NOTE: anomaly_detection.zip is built by `flink/build.sh` (step 1).
# Run `bash flink/build.sh` before `terraform apply`.

# ── Flink Application IAM Role ────────────────────────────────────

data "aws_iam_policy_document" "flink_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    effect  = "Allow"

    principals {
      type        = "Service"
      identifiers = ["kinesisanalytics.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "flink" {
  name               = "${var.project_name}-flink-role"
  assume_role_policy = data.aws_iam_policy_document.flink_assume_role.json

  tags = {
    Name = "${var.project_name}-flink-role"
  }
}

# ── Flink IAM Role Policy ────────────────────────────────────────

data "aws_iam_policy_document" "flink_policy" {
  # KDS Read — main stream (source)
  statement {
    sid    = "KDSReadMainStream"
    effect = "Allow"
    actions = [
      "kinesis:GetRecords",
      "kinesis:GetShardIterator",
      "kinesis:DescribeStream",
      "kinesis:DescribeStreamSummary",
      "kinesis:ListShards",
      "kinesis:ListStreams",
      "kinesis:SubscribeToShard",
    ]
    resources = [aws_kinesis_stream.main.arn]
  }

  # KDS Write — alert stream (sink)
  statement {
    sid    = "KDSWriteAlertStream"
    effect = "Allow"
    actions = [
      "kinesis:PutRecord",
      "kinesis:PutRecords",
    ]
    resources = [aws_kinesis_stream.alert.arn]
  }

  # S3 Write — alerts prefix
  statement {
    sid    = "S3WriteAlerts"
    effect = "Allow"
    actions = [
      "s3:PutObject",
      "s3:PutObjectAcl",
      "s3:AbortMultipartUpload",
    ]
    resources = ["${aws_s3_bucket.datalake.arn}/alerts/*"]
  }

  # S3 Read — flink-code prefix (application code zip)
  statement {
    sid    = "S3ReadFlinkCode"
    effect = "Allow"
    actions = [
      "s3:GetObject",
    ]
    resources = ["${aws_s3_bucket.datalake.arn}/flink-code/*"]
  }

  # CloudWatch Logs
  statement {
    sid    = "CloudWatchLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogGroups",
      "logs:DescribeLogStreams",
    ]
    resources = ["arn:aws:logs:${var.aws_region}:*:log-group:/aws/kinesis-analytics/*"]
  }
}

resource "aws_iam_role_policy" "flink" {
  name   = "${var.project_name}-flink-policy"
  role   = aws_iam_role.flink.id
  policy = data.aws_iam_policy_document.flink_policy.json
}

# ── CloudWatch Log Group & Stream ────────────────────────────────

resource "aws_cloudwatch_log_group" "flink" {
  name              = "/aws/kinesis-analytics/${var.project_name}-anomaly-detector"
  retention_in_days = 14

  tags = {
    Name = "${var.project_name}-flink-logs"
  }
}

resource "aws_cloudwatch_log_stream" "flink" {
  name           = "flink-application"
  log_group_name = aws_cloudwatch_log_group.flink.name
}

# ── S3 Object: Flink Application Code ZIP ───────────────────────

resource "aws_s3_object" "flink_code" {
  bucket = aws_s3_bucket.datalake.id
  key    = "flink-code/anomaly_detection.zip"
  source = "${path.module}/../../../flink/anomaly_detection.zip"
  etag   = filemd5("${path.module}/../../../flink/anomaly_detection.zip")

  tags = {
    Name = "${var.project_name}-flink-code"
  }

  depends_on = []
}

# ── Managed Flink Application ────────────────────────────────────

resource "aws_kinesisanalyticsv2_application" "detector" {
  name                       = "${var.project_name}-anomaly-detector"
  runtime_environment        = "FLINK-1_18"
  service_execution_role_arn = aws_iam_role.flink.arn
  start_application          = true

  application_code_configuration {
    code_content {
      s3_content_location {
        bucket_arn = aws_s3_bucket.datalake.arn
        file_key   = aws_s3_object.flink_code.key
      }
    }
    code_content_type = "ZIPFILE"
  }

  flink_application_configuration {
    checkpoint_configuration {
      configuration_type    = "CUSTOM"
      checkpointing_enabled = true
      checkpoint_interval   = 60000
    }

    monitoring_configuration {
      configuration_type = "CUSTOM"
      log_level          = "INFO"
      metrics_level      = "APPLICATION"
    }

    parallelism_configuration {
      configuration_type   = "CUSTOM"
      parallelism          = 1
      parallelism_per_kpu  = 1
      auto_scaling_enabled = true
    }
  }

  environment_properties {
    property_group {
      property_group_id = "kinesis.analytics.flink.run.options"

      property {
        key   = "python"
        value = "anomaly_detection.py"
      }

      property {
        key   = "jarfile"
        value = "lib/flink-sql-connector-kinesis-1.18.1.jar"
      }
    }

    property_group {
      property_group_id = "robot-app-config"

      property {
        key   = "kinesis.main.stream"
        value = aws_kinesis_stream.main.name
      }

      property {
        key   = "kinesis.alert.stream"
        value = aws_kinesis_stream.alert.name
      }

      property {
        key   = "s3.alerts.path"
        value = "s3://${aws_s3_bucket.datalake.bucket}/alerts/"
      }

      property {
        key   = "aws.region"
        value = var.aws_region
      }

      property {
        key   = "zscore.threshold"
        value = "3.0"
      }

      property {
        key   = "zscore.sigma.floor"
        value = "0.5"
      }

      property {
        key   = "load.ratio.threshold"
        value = "1.8"
      }

      property {
        key   = "load.ratio.min.temp"
        value = "85.0"
      }
    }
  }

  cloudwatch_logging_options {
    log_stream_arn = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:${aws_cloudwatch_log_group.flink.name}:log-stream:${aws_cloudwatch_log_stream.flink.name}"
  }

  tags = {
    Name = "${var.project_name}-anomaly-detector"
  }
}

# ── Data Source: Current AWS Account ID ──────────────────────────

data "aws_caller_identity" "current" {}
