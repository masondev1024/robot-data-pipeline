# Reference: Kinesis Alert Stream (created in kinesis.tf)
#
# Lambda zip은 apply 직전 수동 빌드 필요:
#   $ cd src/lambda && zip ../../terraform/modules/data_pipeline/lambda_alert.zip alert_handler.py
# (archive_file data source가 빈 zip 생성하는 환경 이슈 우회)

# Lambda Function: Alert Handler
resource "aws_lambda_function" "alert" {
  function_name    = "robot-anomaly-alert-lambda"
  runtime          = "python3.10"
  handler          = "alert_handler.handler"
  filename         = "${path.module}/lambda_alert.zip"
  source_code_hash = filebase64sha256("${path.module}/lambda_alert.zip")
  role             = aws_iam_role.lambda_alert_role.arn
  timeout          = 10

  environment {
    variables = {
      SLACK_WEBHOOK_URL = var.slack_webhook_url
    }
  }

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
