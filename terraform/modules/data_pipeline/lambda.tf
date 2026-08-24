# Reference: Kinesis Alert Stream (created in kinesis.tf)
#
# Lambda zip은 apply 직전 수동 빌드 필요:
#   $ cd src/lambda && zip ../../terraform/modules/data_pipeline/lambda_alert.zip alert_handler.py
# (archive_file data source가 빈 zip 생성하는 환경 이슈 우회)

# Slack Webhook URL is sourced from AWS Secrets Manager (single source of truth).
# 사고 회귀 방지: TF_VAR 미export → default 'CHANGEME' apply 사일런트 실패 방지
# (CLAUDE.md §B: Slack Webhook URL 하드코딩 금지).
data "aws_secretsmanager_secret_version" "slack_webhook" {
  secret_id = "/robot-telemetry/slack-webhook-url"
}

# Lambda Function: Alert Handler
resource "aws_lambda_function" "alert" {
  function_name    = "robot-anomaly-alert-lambda"
  runtime          = "python3.10"
  handler          = "alert_handler.handler"
  filename         = "${path.module}/lambda_alert.zip"
  source_code_hash = filebase64sha256("${path.module}/lambda_alert.zip")
  role             = aws_iam_role.lambda_alert_role.arn
  timeout          = 10

  # 검증 계정은 Lambda account concurrency가 10으로 제한될 수 있으므로
  # 예약 동시성을 기본으로 잡지 않는다. null은 unreserved pool을 보존하며,
  # 운영 계정에서 downstream 보호가 필요할 때만 명시적인 값을 전달한다.
  reserved_concurrent_executions = var.lambda_reserved_concurrency

  environment {
    variables = {
      SLACK_WEBHOOK_URL = data.aws_secretsmanager_secret_version.slack_webhook.secret_string
    }
  }

  depends_on = [aws_iam_role_policy.lambda_alert_policy]

  tags = {
    Name = "robot-anomaly-alert-lambda"
  }
}

# Event Source Mapping: Kinesis Alert Stream → Lambda
# function_response_types: 실패한 개별 record만 재시도 (전체 batch 재처리 회피).
# Lambda handler가 {"batchItemFailures": [{"itemIdentifier": <seq>}, ...]} 반환.
resource "aws_lambda_event_source_mapping" "alert_kds" {
  event_source_arn = aws_kinesis_stream.alert.arn
  function_name    = aws_lambda_function.alert.arn
  # TRIM_HORIZON: KDS down/up 사이클 후 mapping 재활성화 시 backlog 회수 보장.
  # LATEST 였으면 2026-05-02 사고처럼 17건 alert backlog 가 skip 됐을 것.
  # ForceNew 속성이라 라이브와 정합 (drift 회복 시 mapping 재생성 회피).
  starting_position       = "TRIM_HORIZON"
  batch_size              = 10
  function_response_types = ["ReportBatchItemFailures"]

  depends_on = [aws_iam_role_policy.lambda_alert_policy]
}
