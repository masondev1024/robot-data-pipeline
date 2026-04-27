# ⚠️ DATA-ONLY DEPLOY: 이 파일은 EKS 권한 부재 상황에서 비EKS 리소스만 남긴 버전입니다.
# 원본 전체 iam.tf는 iam.tf.full-backup 에 보존. EKS 권한 받으면 mv iam.tf.full-backup iam.tf 로 복구.

# ── Firehose Delivery Role (Firehose → S3) ──────────────────────

data "aws_iam_policy_document" "firehose_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    effect  = "Allow"

    principals {
      type        = "Service"
      identifiers = ["firehose.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "firehose_delivery_role" {
  name               = "${var.project_name}-firehose-delivery"
  assume_role_policy = data.aws_iam_policy_document.firehose_assume_role.json
}

data "aws_iam_policy_document" "firehose_delivery" {
  statement {
    effect = "Allow"
    actions = [
      "s3:PutObject",
      "s3:GetBucketLocation",
      "s3:ListBucket",
      "s3:AbortMultipartUpload",
    ]
    resources = [
      aws_s3_bucket.datalake.arn,
      "${aws_s3_bucket.datalake.arn}/*",
    ]
  }

  statement {
    effect = "Allow"
    actions = [
      "glue:GetTable",
      "glue:GetTableVersion",
      "glue:GetTableVersions",
    ]
    resources = ["*"]
  }

  # Firehose KDS source 읽기 권한 — kinesis_source_configuration에 필요
  statement {
    effect = "Allow"
    actions = [
      "kinesis:DescribeStream",
      "kinesis:GetShardIterator",
      "kinesis:GetRecords",
      "kinesis:ListShards",
    ]
    resources = [aws_kinesis_stream.main.arn]
  }
}

resource "aws_iam_role_policy" "firehose_delivery" {
  name   = "firehose-delivery-policy"
  role   = aws_iam_role.firehose_delivery_role.id
  policy = data.aws_iam_policy_document.firehose_delivery.json
}

# ── Lambda Alert Handler Role ──────────────────────────────────
# NOTE: SSM portal-url 권한은 SSM 비활성 상태이므로 제거 (나중에 복구 시 다시 추가)

resource "aws_iam_role" "lambda_alert_role" {
  name = "${var.project_name}-lambda-alert-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy" "lambda_alert_policy" {
  name = "lambda-alert-policy"
  role = aws_iam_role.lambda_alert_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["kinesis:GetRecords", "kinesis:GetShardIterator", "kinesis:DescribeStream", "kinesis:ListShards"]
        Resource = [aws_kinesis_stream.alert.arn]
      },
      # ⚠️ DATA-ONLY DEPLOY: SNS 비활성화. 복구 시 다시 추가.
      # {
      #   Effect   = "Allow"
      #   Action   = ["sns:Publish"]
      #   Resource = [aws_sns_topic.alerts.arn]
      # },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = ["arn:aws:logs:*:*:*"]
      }
    ]
  })
}
