resource "aws_sns_topic" "alerts" {
  name = "${var.project_name}-anomaly-alerts"
}

# Note: Slack subscription is usually handled via Chatbot or a manual webhook integration.
# Here we just create the topic.
