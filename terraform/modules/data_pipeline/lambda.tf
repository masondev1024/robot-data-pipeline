# Reference: Kinesis Alert Stream (created in kinesis.tf)

# ⚠️ DATA-ONLY DEPLOY: archive_file 데이터 소스가 빈 zip 생성하는 알려진 버그 발생.
# 우회: lambda_alert.zip을 수동으로 생성한 뒤 직접 참조 (사전 작업 필요).
#   $ cd src/lambda && zip ../../terraform/modules/data_pipeline/lambda_alert.zip alert_handler.py
# 복구 시 archive_file 다시 사용 가능한지 검증 필요.

# Lambda Function: Alert Handler
resource "aws_lambda_function" "alert" {
  function_name    = "robot-anomaly-alert-lambda"
  runtime          = "python3.10"
  handler          = "alert_handler.handler"
  filename         = "${path.module}/lambda_alert.zip"
  source_code_hash = filebase64sha256("${path.module}/lambda_alert.zip")
  role             = aws_iam_role.lambda_alert_role.arn

  # ⚠️ DATA-ONLY DEPLOY: SNS 비활성화 상태이므로 SNS_TOPIC_ARN 미주입.
  # 복구 시 environment 블록 다시 추가 필요.
  # environment {
  #   variables = {
  #     SNS_TOPIC_ARN = aws_sns_topic.alerts.arn
  #   }
  # }

  depends_on = [aws_iam_role_policy.lambda_alert_policy]

  tags = {
    Name = "robot-anomaly-alert-lambda"
  }
}

# Event Source Mapping: Kinesis Alert Stream → Lambda
resource "aws_lambda_event_source_mapping" "alert_kds" {
  event_source_arn  = aws_kinesis_stream.alert.arn
  function_name     = aws_lambda_function.alert.arn
  starting_position = "LATEST"
  batch_size        = 10

  depends_on = [aws_iam_role_policy.lambda_alert_policy]
}
