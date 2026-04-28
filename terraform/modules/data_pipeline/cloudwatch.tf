# CloudWatch Alarm for Firehose DLQ
# This requires a metric filter or a custom metric to monitor the specific S3 prefix.
# A simpler way is to monitor Firehose DeliveryErrors.

resource "aws_cloudwatch_metric_alarm" "firehose_delivery_errors" {
  alarm_name          = "${var.project_name}-firehose-delivery-errors"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = "1"
  metric_name         = "DeliveryToS3.Success"
  namespace           = "AWS/Firehose"
  period              = "300"
  statistic           = "Average"
  threshold           = "95" # 성공률이 95% 미만일 때 알람
  alarm_description   = "Firehose delivery to S3 success rate is low"
  actions_enabled     = true
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    DeliveryStreamName = aws_kinesis_firehose_delivery_stream.main.name
  }
}
