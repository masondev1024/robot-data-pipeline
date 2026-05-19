# CloudWatch Alarm: Firehose 적재 실패율
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
  statistic           = "Average"
  threshold           = "0.95"
  treat_missing_data  = "notBreaching"
  alarm_description   = "Firehose DeliveryToS3.Success ratio < 0.95 (즉 < 95%) — Lambda 직접 invoke 로 Slack 알림. 메트릭은 0~1 ratio 라 threshold 도 ratio 단위."
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

# Carry-over: Generator put_records_giving_up log filter alarm.
# 전제 조건: FluentBit / CloudWatch Container Insights 로 generator pod stdout 이
# CloudWatch Logs 에 forwarding 되어야 함. 현재 클러스터에 logging agent 미배포
# → 별도 PR 에서 (1) FluentBit DaemonSet (2) aws_cloudwatch_log_metric_filter
# pattern '{ $.event = "put_records_giving_up" }' (3) metric alarm 순으로 추가.
