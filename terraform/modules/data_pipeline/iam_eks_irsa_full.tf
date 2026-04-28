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

  statement {
    sid    = "GlueSchemaRegistryRead"
    effect = "Allow"
    actions = [
      "glue:GetSchema",
      "glue:GetSchemaVersion",
      "glue:GetSchemaByDefinition",
      "glue:GetRegistry",
      "glue:ListSchemas",
    ]
    resources = ["*"]
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
      aws_s3_bucket.datalake.arn,
      "${aws_s3_bucket.datalake.arn}/*",
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

  statement {
    sid    = "SSMGetGrafanaUrl"
    effect = "Allow"
    actions = [
      "ssm:GetParameter",
    ]
    resources = [
      "arn:aws:ssm:${var.aws_region}:*:parameter/robot-telemetry/grafana-url",
    ]
  }
}

resource "aws_iam_role_policy" "api_permissions" {
  name   = "api-permissions-policy"
  role   = aws_iam_role.api_irsa.id
  policy = data.aws_iam_policy_document.api_permissions.json
}

# ── Lambda Alert Handler Role ──────────────────────────────────

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
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = ["arn:aws:ssm:${var.aws_region}:*:parameter/robot-telemetry/portal-url"]
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = ["arn:aws:logs:*:*:*"]
      }
    ]
  })
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

# ── Airflow Worker IRSA (DAG: Athena + S3 + SNS + Bedrock) ─────────

data "aws_iam_policy_document" "airflow_assume_role" {
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
      # Airflow Helm chart의 default worker SA (KubernetesExecutor가 Worker Pod 띄울 때 사용)
      values = ["system:serviceaccount:airflow:airflow-worker"]
    }
  }
}

resource "aws_iam_role" "airflow_irsa" {
  name               = "${var.project_name}-airflow-irsa"
  assume_role_policy = data.aws_iam_policy_document.airflow_assume_role.json
}

data "aws_iam_policy_document" "airflow_permissions" {
  statement {
    sid    = "AthenaQuery"
    effect = "Allow"
    actions = [
      "athena:StartQueryExecution",
      "athena:GetQueryExecution",
      "athena:GetQueryResults",
      "athena:GetWorkGroup",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "GlueCatalogRead"
    effect = "Allow"
    actions = [
      "glue:GetDatabase",
      "glue:GetTable",
      "glue:GetTables",
      "glue:GetPartition",
      "glue:GetPartitions",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "S3DataLakeReadWriteDelete"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject", # 멱등성: silver/gold 파티션 삭제 후 INSERT
      "s3:GetBucketLocation",
      "s3:ListBucket",
    ]
    resources = [
      aws_s3_bucket.datalake.arn,
      "${aws_s3_bucket.datalake.arn}/*",
    ]
  }

  statement {
    sid    = "SNSDQAlert"
    effect = "Allow"
    actions = [
      "sns:Publish",
    ]
    resources = [aws_sns_topic.alerts.arn]
  }

  statement {
    sid    = "BedrockInvoke"
    effect = "Allow"
    actions = [
      "bedrock:InvokeModel",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "airflow_permissions" {
  name   = "airflow-permissions-policy"
  role   = aws_iam_role.airflow_irsa.id
  policy = data.aws_iam_policy_document.airflow_permissions.json
}

# ── Grafana IRSA (Athena + CloudWatch Data Source) ─────────────────

data "aws_iam_policy_document" "grafana_assume_role" {
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
      values   = ["system:serviceaccount:monitoring:grafana"]
    }
  }
}

resource "aws_iam_role" "grafana_irsa" {
  name               = "${var.project_name}-grafana-irsa"
  assume_role_policy = data.aws_iam_policy_document.grafana_assume_role.json
}

data "aws_iam_policy_document" "grafana_permissions" {
  statement {
    sid    = "AthenaQuery"
    effect = "Allow"
    actions = [
      "athena:ListDatabases",
      "athena:ListTableMetadata",
      "athena:GetDatabase",
      "athena:GetTableMetadata",
      "athena:GetQueryExecution",
      "athena:GetQueryResults",
      "athena:GetQueryResultsStream",
      "athena:GetWorkGroup",
      "athena:ListWorkGroups",
      "athena:StartQueryExecution",
      "athena:StopQueryExecution",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "GlueCatalogRead"
    effect = "Allow"
    actions = [
      "glue:GetDatabase",
      "glue:GetDatabases",
      "glue:GetTable",
      "glue:GetTables",
      "glue:GetPartition",
      "glue:GetPartitions",
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
      aws_s3_bucket.datalake.arn,
      "${aws_s3_bucket.datalake.arn}/*",
    ]
  }

  statement {
    sid    = "CloudWatchMetrics"
    effect = "Allow"
    actions = [
      "cloudwatch:DescribeAlarmsForMetric",
      "cloudwatch:DescribeAlarmHistory",
      "cloudwatch:DescribeAlarms",
      "cloudwatch:ListMetrics",
      "cloudwatch:GetMetricStatistics",
      "cloudwatch:GetMetricData",
      "cloudwatch:GetInsightRuleReport",
      "logs:DescribeLogGroups",
      "logs:GetLogGroupFields",
      "logs:StartQuery",
      "logs:StopQuery",
      "logs:GetQueryResults",
      "logs:GetLogEvents",
      "ec2:DescribeTags",
      "ec2:DescribeInstances",
      "ec2:DescribeRegions",
      "tag:GetResources",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "XRayRead"
    effect = "Allow"
    actions = [
      "xray:BatchGetTraces",
      "xray:GetServiceGraph",
      "xray:GetTraceGraph",
      "xray:GetTraceSummaries",
      "xray:GetGroups",
      "xray:GetGroup",
      "xray:GetTimeSeriesServiceStatistics",
      "xray:ListTagsForResource",
      "xray:GetInsightSummaries",
      "xray:GetInsight",
      "xray:GetInsightEvents",
      "xray:GetInsightImpactGraph",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "grafana_permissions" {
  name   = "grafana-permissions-policy"
  role   = aws_iam_role.grafana_irsa.id
  policy = data.aws_iam_policy_document.grafana_permissions.json
}
