data "aws_s3_bucket" "existing" {
  bucket = "de-ai-06-827913617635-ap-northeast-2-an"
}

# ── Generator IRSA Role (EKS Pod → Kinesis) ─────────────────────

data "aws_iam_policy_document" "generator_assume_role" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    effect  = "Allow"

    principals {
      type        = "Federated"
      identifiers = [var.eks_oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${trimprefix(var.eks_oidc_issuer_url, "https://")}:sub"
      values   = ["system:serviceaccount:robot-telemetry:generator-sa"]
    }
  }
}

resource "aws_iam_role" "generator_irsa" {
  name               = "${var.project_name}-generator-irsa"
  assume_role_policy = data.aws_iam_policy_document.generator_assume_role.json
}

data "aws_iam_policy_document" "generator_kinesis" {
  statement {
    effect    = "Allow"
    actions   = ["kinesis:PutRecord", "kinesis:PutRecords", "kinesis:DescribeStream"]
    resources = [aws_kinesis_stream.main.arn]
  }

  statement {
    effect    = "Allow"
    actions   = ["kinesis:PutRecord", "kinesis:PutRecords"]
    resources = [aws_kinesis_stream.alert.arn]
  }
}

resource "aws_iam_role_policy" "generator_kinesis" {
  name   = "generator-kinesis-policy"
  role   = aws_iam_role.generator_irsa.id
  policy = data.aws_iam_policy_document.generator_kinesis.json
}

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
      data.aws_s3_bucket.existing.arn,
      "${data.aws_s3_bucket.existing.arn}/*",
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
}

resource "aws_iam_role_policy" "firehose_delivery" {
  name   = "firehose-delivery-policy"
  role   = aws_iam_role.firehose_delivery_role.id
  policy = data.aws_iam_policy_document.firehose_delivery.json
}

# ── AI Query API IRSA Role (EKS Pod → Athena + Bedrock) ─────────

data "aws_iam_policy_document" "api_assume_role" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    effect  = "Allow"

    principals {
      type        = "Federated"
      identifiers = [var.eks_oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${trimprefix(var.eks_oidc_issuer_url, "https://")}:sub"
      values   = ["system:serviceaccount:robot-telemetry:api-sa"]
    }
  }
}

resource "aws_iam_role" "api_irsa" {
  name               = "${var.project_name}-api-irsa"
  assume_role_policy = data.aws_iam_policy_document.api_assume_role.json
}

data "aws_iam_policy_document" "api_permissions" {
  statement {
    sid    = "AthenaQueryAccess"
    effect = "Allow"
    actions = [
      "athena:StartQueryExecution",
      "athena:GetQueryExecution",
      "athena:GetQueryResults",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "S3AthenaResults"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:GetBucketLocation",
      "s3:ListBucket",
    ]
    resources = [
      data.aws_s3_bucket.existing.arn,
      "${data.aws_s3_bucket.existing.arn}/*",
    ]
  }

  statement {
    sid    = "GlueCatalogRead"
    effect = "Allow"
    actions = [
      "glue:GetTable",
      "glue:GetDatabase",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "BedrockInvoke"
    effect = "Allow"
    actions = [
      "bedrock:InvokeModel",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "SageMakerInvokeEndpoint"
    effect = "Allow"
    actions = [
      "sagemaker:InvokeEndpoint",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "api_permissions" {
  name   = "api-permissions-policy"
  role   = aws_iam_role.api_irsa.id
  policy = data.aws_iam_policy_document.api_permissions.json
}

# ── X-Ray Tracing Policy (Generator + API IRSA) ─────────────────

resource "aws_iam_role_policy" "xray_generator" {
  name = "robot-telemetry-xray-policy"
  role = aws_iam_role.generator_irsa.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "xray:PutTraceSegments",
        "xray:PutTelemetryRecords",
        "xray:GetSamplingRules",
        "xray:GetSamplingTargets"
      ]
      Resource = "*"
    }]
  })
}

resource "aws_iam_role_policy" "xray_api" {
  name = "robot-telemetry-xray-policy"
  role = aws_iam_role.api_irsa.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "xray:PutTraceSegments",
        "xray:PutTelemetryRecords",
        "xray:GetSamplingRules",
        "xray:GetSamplingTargets"
      ]
      Resource = "*"
    }]
  })
}
