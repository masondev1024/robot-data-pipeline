resource "aws_lambda_function" "alert_handler" {
  filename      = "${path.module}/../../../src/lambda/alert_handler.zip" # Placeholder, will be built by CI/CD
  function_name = "${var.project_name}-anomaly-alert-lambda"
  role          = aws_iam_role.lambda_alert_role.arn
  handler       = "alert_handler.lambda_handler"
  runtime       = "python3.11"

  environment {
    variables = {
      SNS_TOPIC_ARN = aws_sns_topic.alerts.arn
      PROJECT_NAME  = var.project_name
    }
  }
}

resource "aws_lambda_event_source_mapping" "kinesis_trigger" {
  event_source_arn  = aws_kinesis_stream.alert.arn
  function_name     = aws_lambda_function.alert_handler.arn
  starting_position = "LATEST"
}
