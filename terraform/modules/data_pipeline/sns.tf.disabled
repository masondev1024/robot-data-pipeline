# SNS Topic for Robot Anomaly Alerts
resource "aws_sns_topic" "alerts" {
  name = "robot-anomaly-alerts"

  tags = {
    Name = "robot-anomaly-alerts"
  }
}

# SNS Topic Subscription: Slack Webhook
resource "aws_sns_topic_subscription" "slack" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "https"
  endpoint  = var.slack_webhook_url
}
