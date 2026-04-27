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

# ── Managed Flink Application (Manual Deployment) ────────────────
# NOTE: Terraform does not fully support aws_kinesisanalyticsv2_application configuration.
# Deploy Flink app manually after terraform apply:
#
#   aws kinesisanalyticsv2 create-application \
#     --application-name robot-telemetry-anomaly-detector \
#     --runtime-environment FLINK_1_18 \
#     --service-execution-role-arn arn:aws:iam::ACCOUNT_ID:role/robot-telemetry-flink-role \
#     --application-code-configuration '{
#         "CodeContentType": "ZIPFILE",
#         "CodeContent": {
#           "S3ContentLocation": {
#             "BucketARN": "arn:aws:s3:::de-ai-06-smartfactory-bucket",
#             "FileKey": "flink-code/anomaly_detection.zip"
#           }
#         }
#       }' \
#     --region eu-west-1
#
# OR use flink/deploy.sh script (to be created) for automated deployment.

# ── Data Source: Current AWS Account ID ──────────────────────────

data "aws_caller_identity" "current" {}
