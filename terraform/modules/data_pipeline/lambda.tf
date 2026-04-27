# Reference: Kinesis Alert Stream (created in kinesis.tf)

# Archive Lambda Handler Code
data "archive_file" "alert_handler" {
  type        = "zip"
  source_file = "${path.module}/../../src/lambda/alert_handler.py"
  output_path = "${path.module}/lambda_alert.zip"
}

# Lambda Function: Alert Handler
resource "aws_lambda_function" "alert" {
  function_name    = "robot-anomaly-alert-lambda"
  runtime          = "python3.10"
  handler          = "alert_handler.handler"
  filename         = data.archive_file.alert_handler.output_path
  source_code_hash = data.archive_file.alert_handler.output_base64sha256
  role             = aws_iam_role.lambda_alert_role.arn

  environment {
    variables = {
      SNS_TOPIC_ARN = aws_sns_topic.alerts.arn
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
