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

  # 예약 동시성은 계정별 Lambda concurrency quota가 10인 신규 계정에서
  # PutFunctionConcurrency 자체가 거부될 수 있다(계정 최소 unreserved=10).
  # KDS event-source mapping의 batch/backoff가 소비율을 제한하므로, 별도
  # 예약값 대신 unreserved concurrency를 사용해 배포 가능성과 계정 portability를
  # 우선한다. 필요 시 quota 증액 후 환경별 Terraform 변수로 예약값을 추가한다.

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
