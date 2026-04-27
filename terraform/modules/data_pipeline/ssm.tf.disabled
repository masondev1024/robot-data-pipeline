resource "aws_ssm_parameter" "portal_url" {
  name  = "/${var.project_name}/portal-url"
  type  = "String"
  value = "PENDING"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "grafana_url" {
  name  = "/${var.project_name}/grafana-url"
  type  = "String"
  value = "PENDING"

  lifecycle {
    ignore_changes = [value]
  }
}
