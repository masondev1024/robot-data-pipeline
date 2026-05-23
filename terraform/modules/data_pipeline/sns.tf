# SNS Topic for Robot Anomaly Alerts
# 인프라는 보존하지만 현재 미사용. Lambda → Slack 직통 구조로 운영 중.
resource "aws_sns_topic" "alerts" {
  name = "robot-anomaly-alerts"

  tags = {
    Name = "robot-anomaly-alerts"
  }
}
