# CloudWatch Alarm: Firehose S3 전달 상태
#
# alarm action 경로 변경 (2026-04-30): SNS robot-anomaly-alerts → Lambda 직접 invoke.
# 이유: SNS HTTPS subscription 이 04-28 PendingConfirmation 영구 고착 후 04-30 IaC 에서
# 제거됨 → SNS topic 자체는 보존되지만 수신자 없음 → 알람 발화해도 Slack 미도달.
# Lambda(alert_handler)에 CloudWatch Alarm event 분기 추가하여 Slack 직접 POST 보장.
#
# 자동 회복 강화: evaluation_periods 1 → 2 + datapoints_to_alarm 2 + treat_missing_data
# notBreaching. 어제 한 번 발화 후 23시간 ALARM 머무는 stuck 패턴 방지.
resource "aws_cloudwatch_metric_alarm" "firehose_delivery_errors" {
  alarm_name          = "${var.project_name}-firehose-delivery-errors"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = "2"
  datapoints_to_alarm = "2"
  metric_name         = "DeliveryToS3.Success"
  namespace           = "AWS/Firehose"
  period              = "300"
  statistic           = "Minimum"
  threshold           = "1"
  treat_missing_data  = "notBreaching"
  alarm_description   = "Firehose DeliveryToS3.Success is the count of successful S3 put commands. Alert when an active 5-minute period has no successful put command. Freshness is monitored separately."
  actions_enabled     = true
  alarm_actions       = [aws_lambda_function.alert.arn]
  ok_actions          = [aws_lambda_function.alert.arn]

  dimensions = {
    DeliveryStreamName = aws_kinesis_firehose_delivery_stream.main.name
  }
}

# DeliveryToS3.DataFreshness is an age in seconds, not a success ratio.
# This catches a buffered or retrying delivery path even when the last delivery
# period happened to contain one successful object.
resource "aws_cloudwatch_metric_alarm" "firehose_data_freshness" {
  alarm_name          = "${var.project_name}-firehose-data-freshness"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  datapoints_to_alarm = "2"
  metric_name         = "DeliveryToS3.DataFreshness"
  namespace           = "AWS/Firehose"
  period              = "300"
  statistic           = "Maximum"
  threshold           = var.firehose_data_freshness_threshold_seconds
  treat_missing_data  = "notBreaching"
  alarm_description   = "Firehose S3 delivery data age exceeded the freshness SLO (seconds)."
  actions_enabled     = true
  alarm_actions       = [aws_lambda_function.alert.arn]
  ok_actions          = [aws_lambda_function.alert.arn]

  dimensions = {
    DeliveryStreamName = aws_kinesis_firehose_delivery_stream.main.name
  }
}

# CloudWatch Alarm 이 Lambda 를 직접 invoke 하도록 permission 부여.
# alarm_actions/ok_actions 에 Lambda ARN 만 명시해도 호출 권한이 없으면 무시됨.
resource "aws_lambda_permission" "alarm_invoke_alert" {
  statement_id  = "AllowCloudWatchAlarmInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.alert.function_name
  principal     = "lambda.alarms.cloudwatch.amazonaws.com"
  source_arn    = aws_cloudwatch_metric_alarm.firehose_delivery_errors.arn
}

resource "aws_lambda_permission" "alarm_invoke_alert_firehose_freshness" {
  statement_id  = "AllowCloudWatchAlarmInvokeFirehoseFreshness"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.alert.function_name
  principal     = "lambda.alarms.cloudwatch.amazonaws.com"
  source_arn    = aws_cloudwatch_metric_alarm.firehose_data_freshness.arn
}

# CloudWatch Alarm: KDS main write throttle
#
# 1000 robots production 전환 시 신규: WriteProvisionedThroughputExceeded 가
# 1건이라도 발생하면 즉시 Slack 알림. 4 shard 환경 peak 1000 rec/s 의 25% 사용률
# 이라 정상 운영 0건 기대 — 발생 시 partition key skew (60%+ hot shard) 또는
# 부하 증가 신호 → describe-stream-summary 로 OpenShardCount 확인 + reshard 검토.
resource "aws_cloudwatch_metric_alarm" "kds_main_write_throttle" {
  alarm_name          = "${var.project_name}-kds-main-write-throttle"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  datapoints_to_alarm = "1"
  metric_name         = "WriteProvisionedThroughputExceeded"
  namespace           = "AWS/Kinesis"
  period              = "60"
  statistic           = "Sum"
  threshold           = "0"
  treat_missing_data  = "notBreaching"
  alarm_description   = "KDS main stream write throttle (>0 events/min). 1000 robots production 전환 후 신규 — partition key skew 또는 shard 부족 신호."
  actions_enabled     = true
  alarm_actions       = [aws_lambda_function.alert.arn]
  ok_actions          = [aws_lambda_function.alert.arn]

  dimensions = {
    StreamName = aws_kinesis_stream.main.name
  }
}

resource "aws_lambda_permission" "alarm_invoke_alert_kds_throttle" {
  statement_id  = "AllowCloudWatchAlarmInvokeKDSThrottle"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.alert.function_name
  principal     = "lambda.alarms.cloudwatch.amazonaws.com"
  source_arn    = aws_cloudwatch_metric_alarm.kds_main_write_throttle.arn
}

# CloudWatch Alarm: KDS consumer lag
#
# IteratorAgeMilliseconds is the age of the last record returned to a consumer.
# A rising value is a direct signal that Flink/Firehose is not keeping up with
# the producer, while write throttles alone only describe the producer side.
resource "aws_cloudwatch_metric_alarm" "kds_main_iterator_age" {
  alarm_name          = "${var.project_name}-kds-iterator-age"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "3"
  datapoints_to_alarm = "2"
  metric_name         = "GetRecords.IteratorAgeMilliseconds"
  namespace           = "AWS/Kinesis"
  period              = "60"
  statistic           = "Maximum"
  threshold           = var.kds_iterator_age_threshold_milliseconds
  treat_missing_data  = "notBreaching"
  alarm_description   = "KDS consumer iterator age exceeded the streaming freshness SLO (milliseconds)."
  actions_enabled     = true
  alarm_actions       = [aws_lambda_function.alert.arn]
  ok_actions          = [aws_lambda_function.alert.arn]

  dimensions = {
    StreamName = aws_kinesis_stream.main.name
  }
}

resource "aws_lambda_permission" "alarm_invoke_alert_kds_iterator_age" {
  statement_id  = "AllowCloudWatchAlarmInvokeKDSIteratorAge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.alert.function_name
  principal     = "lambda.alarms.cloudwatch.amazonaws.com"
  source_arn    = aws_cloudwatch_metric_alarm.kds_main_iterator_age.arn
}

# Carry-over: Generator put_records_giving_up log filter alarm.
# 전제 조건: FluentBit / CloudWatch Container Insights 로 generator pod stdout 이
# CloudWatch Logs 에 forwarding 되어야 함. 현재 클러스터에 logging agent 미배포
# → 별도 PR 에서 (1) FluentBit DaemonSet (2) aws_cloudwatch_log_metric_filter
# pattern '{ $.event = "put_records_giving_up" }' (3) metric alarm 순으로 추가.
