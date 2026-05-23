# AWS X-Ray Group + Sampling Rule

resource "aws_xray_group" "main" {
  group_name        = "robot-telemetry-traces"
  filter_expression = "service(\"robot-telemetry-api\") OR service(\"robot-telemetry-generator\")"

  insights_configuration {
    insights_enabled      = true
    notifications_enabled = false
  }
}

resource "aws_xray_sampling_rule" "main" {
  rule_name      = "robot-telemetry-sampling"
  priority       = 1000
  reservoir_size = 1
  fixed_rate     = 0.05
  url_path       = "*"
  host           = "*"
  http_method    = "*"
  service_name   = "*"
  service_type   = "*"
  resource_arn   = "*"
  version        = 1
}
