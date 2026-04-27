variable "project_name" {
  type = string
}

variable "aws_region" {
  type = string
}

# ⚠️ DATA-ONLY DEPLOY: EKS OIDC 변수는 더미값. 복구 시 default 제거하고 main.tf에서 다시 주입.
variable "eks_oidc_provider_arn" {
  type    = string
  default = "arn:aws:iam::000000000000:oidc-provider/DUMMY"
}

variable "eks_oidc_issuer_url" {
  type    = string
  default = "https://oidc.eks.eu-west-1.amazonaws.com/id/DUMMY"
}

variable "environment" {
  type    = string
  default = "dev"
}

variable "slack_webhook_url" {
  description = "Slack Webhook URL for alert notifications (injected from .env)"
  type        = string
  sensitive   = true
  default     = "DUMMY"  # ⚠️ DATA-ONLY DEPLOY: SNS 비활성화 상태이므로 미사용
}

# ⚠️ DATA-ONLY DEPLOY: Grafana 비활성화 상태이므로 default 더미. 복구 시 default 제거.
variable "grafana_admin_password" {
  description = "Grafana admin password (managed by AWS Secrets Manager)"
  type        = string
  sensitive   = true
  default     = "DUMMY"
}
